import os
import json
import uuid
import random
import string
import logging
import subprocess
from datetime import datetime, date, timedelta

import openpyxl
import pandas as pd  # type: ignore
from PIL import Image, ImageDraw, ImageFont

from django.conf import settings
from django.core.files import File
from django.db import IntegrityError
from django.db.models import Q, Count
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import status, viewsets, generics
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView
from distutils.util import strtobool
from .models import (
    Employee,
    DoctorVideo,
    Doctor,
    EmployeeLoginHistory,
    VideoTemplates,
    DoctorOutputVideo,
    ImageContent,
    Brand,
    TemplateBrandPosition
)
from .serializers import (
    EmployeeLoginSerializer,
    EmployeeSerializer,
    DoctorSerializer,
    DoctorVideoSerializer,
    VideoTemplatesSerializer,
    DoctorOutputVideoSerializer,
    ImageContentSerializer,
    ImageTemplateSerializer,
    BrandSerializer,
    TemplateBrandPositionSerializer
)

# Celery task
try:
    from employee_app.tasks import generate_custom_video_task
except Exception:
    class _NoopTask:
        def delay(self, *a, **kw):
            pass
    generate_custom_video_task = _NoopTask()

# ------------------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------------------
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------

def parse_css_shadow(shadow_str):
    """Parse CSS-like text-shadow: '2px 2px 4px rgba(0,0,0,0.7)' -> dict or None"""
    if shadow_str == 'none' or not shadow_str:
        return None
    try:
        if 'rgba' in shadow_str:
            rgba_start = shadow_str.find('rgba(')
            rgba_end = shadow_str.find(')', rgba_start)
            rgba_str = shadow_str[rgba_start+5:rgba_end]
            rgba_values = [float(x.strip()) for x in rgba_str.split(',')]
            shadow_color = (int(rgba_values[0]), int(rgba_values[1]), int(rgba_values[2]))
            offset_part = shadow_str[:rgba_start].strip()
            offsets = offset_part.replace('px', '').split()
            if len(offsets) >= 2:
                return {
                    'offset_x': int(float(offsets[0])),
                    'offset_y': int(float(offsets[1])),
                    'color': shadow_color
                }
        elif 'px' in shadow_str:
            parts = shadow_str.replace('px', '').split()
            if len(parts) >= 2:
                return {
                    'offset_x': int(float(parts[0])),
                    'offset_y': int(float(parts[1])),
                    'color': (128, 128, 128)
                }
    except:  # noqa: E722
        pass
    return {'offset_x': 2, 'offset_y': 2, 'color': (128, 128, 128)}


def _ff_esc(s: str) -> str:
    s = str(s or "")
    s = s.replace("\\", "\\\\")  # backslash first
    s = s.replace(":", r"\:")
    s = s.replace("'", r"\'")
    s = s.replace("%", r"\%")
    return s

def _num_or_expr(v, default="0"):
    v = str(v).strip()
    return v if v and not v.lstrip("+-").isdigit() else str(int(v or default))

# ------------------------------------------------------------------------------
# Pagination
# ------------------------------------------------------------------------------

class Pagination_class(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100

# ------------------------------------------------------------------------------
# Employees & Auth
# ------------------------------------------------------------------------------

class EmployeeViewSet(viewsets.ModelViewSet):
    queryset = Employee.objects.all()
    serializer_class = EmployeeSerializer

def get_tokens_for_employee(employee):
    refresh = RefreshToken.for_user(employee)
    refresh.access_token.set_exp(lifetime=timedelta(hours=1))
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
        'access_token_exp': refresh.access_token.payload['exp'],
    }

@api_view(['POST'])
def employee_login_api(request):
    serializer = EmployeeLoginSerializer(data=request.data)
    if serializer.is_valid():
        employee_id = serializer.validated_data['employee_id']
        try:
            employee = Employee.objects.get(employee_id=employee_id)

            if not employee.status:
                return Response({
                    'status': 'error',
                    'message': 'Your account is inactive. Please contact the admin department.'
                }, status=status.HTTP_403_FORBIDDEN)

            employee.login_date = timezone.now()
            employee.has_logged_in = True
            employee.save(update_fields=['login_date', 'has_logged_in'])

            tokens = get_tokens_for_employee(employee)

            EmployeeLoginHistory.objects.create(
                employee=employee,
                employee_identifier=employee.employee_id,
                name=f"{employee.first_name} {employee.last_name}",
                email=employee.email,
                phone=employee.phone,
                department=employee.department,
                user_type=employee.user_type
            )

            return Response({
                'status': 'success',
                'message': 'Login successful',
                'tokens': tokens,
                'employee': {
                    'id': employee.id,
                    'employee_id': employee.employee_id,
                    'name': f"{employee.first_name} {employee.last_name}",
                    'email': employee.email,
                    'department': employee.department,
                    'user_type': employee.user_type
                }
            }, status=status.HTTP_200_OK)

        except Employee.DoesNotExist:
            return Response({'status': 'error', 'message': 'Invalid employee ID'}, status=status.HTTP_401_UNAUTHORIZED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# ------------------------------------------------------------------------------
# Doctors (base)
# ------------------------------------------------------------------------------

@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
def add_doctor(request):
    serializer = DoctorSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response({'status': 'success', 'data': serializer.data}, status=status.HTTP_201_CREATED)
    return Response({'status': 'error', 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

# ------------------------------------------------------------------------------
# Video generation (DoctorVideo)
# ------------------------------------------------------------------------------

class VideoGenViewSet(viewsets.ModelViewSet):
    queryset = DoctorVideo.objects.all()
    serializer_class = DoctorVideoSerializer

    # --- DYNAMIC time-duration parsing brought in from later versions ---
    def parse_time_duration(self, time_duration_str):
        """
        Parse a string like "2-6,65-70" into [(2,6),(65,70)].
        Validates order and non-negative starts.
        """
        if not time_duration_str or not time_duration_str.strip():
            raise ValueError("Time duration cannot be empty")
        try:
            slots = []
            for time_range in time_duration_str.strip().split(','):
                start_str, end_str = time_range.strip().split('-')
                start_time = int(start_str.strip())
                end_time = int(end_str.strip())
                if start_time >= end_time:
                    raise ValueError(f"Start time ({start_time}) must be less than end time ({end_time})")
                if start_time < 0:
                    raise ValueError(f"Start time ({start_time}) cannot be negative")
                slots.append((start_time, end_time))
            return slots
        except ValueError as e:
            if "not enough values" in str(e) or "too many values" in str(e):
                raise ValueError(
                    f"Invalid time duration format: '{time_duration_str}'. "
                    "Use '10-15' or '10-15,46-50'"
                )
            raise
        except Exception as e:
            raise ValueError(f"Error parsing time duration '{time_duration_str}': {str(e)}")

    def perform_create(self, serializer):
        """
        Save DoctorVideo, and enqueue video generation via Celery (new behavior).
        Also records a DoctorOutputVideo with the intended output path.
        """
        logger.info("VideoGenViewSet.perform_create called")
        request = self.request
        doctor = serializer.save()
        logger.info(f"Doctor saved: {doctor.name} (ID: {doctor.id})")

        if not doctor.image:
            logger.warning(f"Doctor {doctor.name} has no image, skipping video generation")
            return

        # Choose template: explicit id or first active
        template_id = request.data.get("template_id")
        template = VideoTemplates.objects.filter(id=template_id).first() if template_id \
            else VideoTemplates.objects.filter(status=True).first()

        if not template:
            logger.error("No template found, aborting video generation")
            return

        # Prepare paths
        output_filename = f"{doctor.id}_{template.id}_output.mp4"
        output_dir = os.path.join(settings.MEDIA_ROOT, "output", str(doctor.employee.id), str(doctor.id))
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, output_filename)
        logger.info(f"Video will be saved to: {output_path}")

        # Enqueue Celery task with dynamic parameters from template
        try:
            generate_custom_video_task.delay(
                doctor.id,
                template.id,
                output_path,
                template.template_video.path,
                doctor.image.path,
                doctor.name,
                doctor.clinic,
                doctor.city,
                doctor.specialization_key,
                template.time_duration,
                doctor.state,
                template.resolution,
                template.base_x_axis,
                template.base_y_axis,
                template.line_spacing,
                template.overlay_x,
                template.overlay_y,
            )
            logger.info("Video generation task enqueued to Celery")

            # Create DB record pointing to the (future) file
            relative_path = os.path.relpath(output_path, settings.MEDIA_ROOT)
            DoctorOutputVideo.objects.create(
                doctor=doctor,
                template=template,
                video_file=relative_path
            )
            logger.info("DoctorOutputVideo record created")

        except Exception as e:
            logger.error(f"Error enqueuing video generation: {e}")

    def generate_custom_video(
        self,
        main_video_path,
        image_path,
        name,
        clinic,
        city,
        specialization_key,
        state,
        output_path,
        time_duration="5-10,45-50",
        resolution="415x410",
        base_x="(main_w/2)-160",
        base_y="(main_h/2)-60",
        line_spacing="60",
        overlay_x="350",
        overlay_y="70"
    ):
        """
        Synchronous FFmpeg composition with dynamic overlay slots and drawtext.
        Kept here for compatibility and for non-Celery flows.
        """
        logger.info(f"Starting video generation for doctor: {name}")

        if not os.path.exists(main_video_path):
            raise Exception(f"Template video not found: {main_video_path}")
        if not os.path.exists(image_path):
            raise Exception(f"Doctor image not found: {image_path}")

        temp_dir = os.path.join(settings.MEDIA_ROOT, "temp")
        os.makedirs(temp_dir, exist_ok=True)

        fps = 30
        fade_duration = 3

        # Dynamic slots
        slots = self.parse_time_duration(time_duration)

        # Create pan/zoom temp clips for each slot
        temp_videos = []
        for i, (start, end) in enumerate(slots):
            duration = end - start
            total_frames = duration * fps
            zoom_effect = (
                f"zoompan=z='1+0.00003*in':"
                f"x='(iw/2)-(iw/zoom/2)':"
                f"y='(ih/2)-(ih/zoom/2)':d={total_frames}:s={resolution}:fps={fps}"
            )
            fade_out_start = max(0, duration - fade_duration)
            fade_effect = f"format=rgba,fade=t=in:st=0:d={fade_duration}:alpha=1,fade=t=out:st={fade_out_start}:d={fade_duration}:alpha=1"
            vf = f"scale={resolution},{zoom_effect},{fade_effect}"
            temp_video = os.path.join(temp_dir, f"temp_image_vid_{i}.mp4")

            try:
                subprocess.run(
                    ["ffmpeg", "-loop", "1", "-i", image_path, "-vf", vf, "-t", str(duration), "-y", temp_video],
                    check=True, capture_output=True, text=True
                )
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to create temp video {i}: {e.stderr}")
                raise Exception(f"Failed to create temp video: {e.stderr}")

            temp_videos.append((temp_video, start, end))

        # Drawtext lines
        text_lines = [str(x or "").strip() for x in [name, specialization_key, clinic, city, state]]


        # Select a font present on the system/container
# Select a font present on the system/container
        font_paths = [
            os.path.join(settings.BASE_DIR, "fonts", "RobotoSlab-Medium.ttf"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",     # Linux
            "/System/Library/Fonts/Arial.ttf",                     # macOS
            r"C:\Windows\Fonts\arial.ttf",                         # Windows (common)
            r"C:\Windows\Fonts\ARIAL.TTF",                         # Windows (fallback)
            "arial.ttf",
        ]

        font = None
        for fp in font_paths:
            if os.path.exists(fp):
                font = fp  # found a real path
                break
        if not font:
            font = "Arial"  # family name for drawtext `font=`

        # Do we have a file path or a family name?
        # Normalize Windows paths for ffmpeg drawtext (forward slashes + escape ':' in drive letters)
        if isinstance(font, str) and (os.path.isabs(font) or font.lower().endswith(".ttf")):
            if os.name == "nt":
                font = font.replace("\\", "/").replace(":", r"\:")
            font_is_path = True
        else:
            font_is_path = False


        # Build drawtext filters

        text_filters = []
        for start, end in slots:
            alpha_expr = f"if(lt(t\\,{start}+3),(t-{start})/3,if(lt(t\\,{end}-3),1,({end}-t)/3))"
            for j, text in enumerate(text_lines):
                if not text:
                    continue
                safe_text = _ff_esc(text)
                x_pos = f"{base_x}"
                y_pos = f"{base_y} + {j}*{line_spacing}"
                if font_is_path:
                    font_part = f"fontfile='{font}':"
                else:
                    font_part = f"font='{font}':"

                drawtext = (
                    f"drawtext=text='{safe_text}':{font_part}fontcolor=black:fontsize=40:"
                    f"x={x_pos}:y={y_pos}:enable='between(t,{start},{end})':alpha='{alpha_expr}'"
                )
                text_filters.append(drawtext)



        ox = _num_or_expr(overlay_x, "0")
        oy = _num_or_expr(overlay_y, "0")
        overlay_x1 = f"(main_w-overlay_w)/2-({ox})"
        overlay_y1 = f"(main_h-overlay_h)/2+({oy})"


        # Build overlay chain dynamically for any number of slots
        overlay_filters = []
        for i, (start, end) in enumerate(slots):
            input_label = "[0:v]" if i == 0 else f"[v{i}]"
            output_label = f"[v{i+1}]"
            overlay_filters.append(
                f"{input_label}[{i+1}:v]overlay=x={overlay_x1}:y={overlay_y1}:enable='between(t,{start},{end})'{output_label}"
            )

        final_input = f"[v{len(slots)}]"
        filter_complex = f"{';'.join(overlay_filters)};{final_input}{','.join(text_filters)}[v]"

        cmd = ["ffmpeg", "-i", main_video_path]
        for temp_video, _, _ in temp_videos:
            cmd.extend(["-i", temp_video])
        # cmd.extend(["-filter_complex", filter_complex, "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-c:a", "copy", "-y", output_path])
        cmd.extend([
                "-filter_complex", filter_complex,
                "-map", "[v]", "-map", "0:a?",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "copy",
                "-movflags", "+faststart",
                "-y", output_path
            ])


        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Final FFmpeg failed: {e.stderr}")
            raise Exception(f"Video generation failed: {e.stderr}")
        finally:
            for temp_video, _, _ in temp_videos:
                if os.path.exists(temp_video):
                    os.remove(temp_video)

class DoctorVideoViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DoctorVideo.objects.all().order_by('-created_at')
    serializer_class = DoctorVideoSerializer
    pagination_class = Pagination_class

# ------------------------------------------------------------------------------
# Bulk uploads
# ------------------------------------------------------------------------------

@api_view(['POST'])
@parser_classes([MultiPartParser])
def bulk_upload_employees(request):
    excel_file = request.FILES.get('file')
    if not excel_file:
        return Response({'error': 'No file provided.'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        df = pd.read_excel(excel_file)
        required = {'first_name', 'last_name', 'email', 'phone', 'department', 'date_joined'}
        if not required.issubset(df.columns):
            return Response({'error': f'Missing required columns: {required - set(df.columns)}'}, status=status.HTTP_400_BAD_REQUEST)

        created, skipped, errors = 0, 0, []

        def generate_employee_id(first_name, last_name):
            base = f"EMP{first_name[0].upper()}{last_name[0].upper()}"
            while True:
                suffix = ''.join(random.choices(string.digits, k=4))
                emp_id = f"{base}{suffix}"
                if not Employee.objects.filter(employee_id=emp_id).exists():
                    return emp_id

        for index, row in df.iterrows():
            row_number = index + 2
            first_name = str(row.get('first_name', '')).strip()
            last_name = str(row.get('last_name', '')).strip()
            email = str(row.get('email', '')).strip()
            phone = str(row.get('phone', '')).strip()

            if not first_name or not last_name or not email:
                errors.append({'row': row_number, 'error': 'Missing first name, last name, email or phone'})
                skipped += 1
                continue

            employee_id = str(row.get('employee_id')).strip()
            data = {
                'employee_id': employee_id or generate_employee_id(first_name, last_name),
                'first_name': first_name,
                'last_name': last_name,
                'email': email,
                'phone': phone,
                'department': row.get('department', '') or 'Unknown',
                'date_joined': row.get('date_joined') if not pd.isna(row.get('date_joined')) else datetime.today().date()
            }
            serializer = EmployeeSerializer(data=data)
            if serializer.is_valid():
                try:
                    serializer.save()
                    created += 1
                except IntegrityError:
                    errors.append({'row': row_number, 'error': 'Duplicate email or other unique constraint'})
                    skipped += 1
            else:
                errors.append({'row': row_number, 'error': serializer.errors})
                skipped += 1

        return Response({'created': created, 'skipped': skipped, 'errors': errors}, status=status.HTTP_201_CREATED)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class DoctorListByEmployee(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        employee_id = request.GET.get('employee_id')
        if not employee_id:
            return Response({"detail": "employee_id is required."}, status=400)
        try:
            employee = Employee.objects.get(employee_id=employee_id)
        except Employee.DoesNotExist:
            return Response({"detail": "Employee not found for this employee_id."}, status=404)
        doctors = Doctor.objects.filter(employee=employee)
        serializer = DoctorSerializer(doctors, many=True)
        return Response(serializer.data)

class DoctorVideoListView(APIView):
    def get(self, request):
        employee_id = request.GET.get('employee_id')
        if not employee_id:
            return Response({"detail": "employee_id is required."}, status=400)
        try:
            employee = Employee.objects.get(employee_id=employee_id)
        except Employee.DoesNotExist:
            return Response({"detail": "Employee not found for this employee_id."}, status=404)
        doctors = DoctorVideo.objects.filter(employee=employee).order_by('-created_at')
        paginator = Pagination_class()
        page = paginator.paginate_queryset(doctors, request)
        serializer = DoctorVideoSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

# ------------------------------------------------------------------------------
# Manual single doctor generation (kept as-is; uses sync generation)
# ------------------------------------------------------------------------------

class DoctorVideoGeneration(APIView):
    def post(self, request):
        doctor_id = request.data.get('id')
        if not doctor_id:
            return Response({"detail": "doctor_id is required."}, status=400)
        try:
            doctor_data = DoctorVideo.objects.get(id=doctor_id)
            generate_video_for_doctor(doctor_data)
            return Response({
                "detail": "Video generation successful.",
                "video_path": request.build_absolute_uri(doctor_data.output_video.url) if doctor_data.output_video else None
            })
        except DoctorVideo.DoesNotExist:
            return Response({"detail": "Doctor not found for this doctor_id."}, status=404)
        except Exception as e:
            return Response({"detail": f"Error during video generation: {str(e)}"}, status=500)

class CustomTokenRefreshView(TokenRefreshView):
    def post(self, request, *args, **kwargs):
        refresh_token = request.data.get('refresh', None)
        if not refresh_token:
            return Response({'status': 'error', 'message': 'Refresh token is required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            refresh = RefreshToken(refresh_token)
            new_refresh_token = str(refresh)
            new_access_token = str(refresh.access_token)
            return Response({
                'status': 'success',
                'message': 'Token refreshed successfully',
                'access': new_access_token,
                'refresh': new_refresh_token,
                'access_token_exp': refresh.access_token.payload['exp'],
            }, status=status.HTTP_200_OK)
        except Exception:
            return Response({'status': 'error', 'message': 'Invalid refresh token'}, status=status.HTTP_401_UNAUTHORIZED)

def generate_video_for_doctor(doctor):
    """Simple hardcoded-template generation path (kept for backward compatibility)."""
    logger.info(f"Generating video for doctor {doctor.name}")
    try:
        if not doctor.image:
            logger.warning(f"No image for doctor {doctor.name}, skipping video.")
            return

        main_video_path = os.path.join(settings.MEDIA_ROOT, "Health111.mp4")
        image_path = doctor.image.path
        output_dir = os.path.join(settings.MEDIA_ROOT, "output")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"{doctor.id}_output.mp4")

        # Reuse the sync path from VideoGenViewSet for consistent visuals
        VideoGenViewSet().generate_custom_video(
            main_video_path=main_video_path,
            image_path=image_path,
            name=doctor.name,
            clinic=doctor.clinic,
            city=doctor.city,
            specialization_key=getattr(doctor, "specialization_key", doctor.specialization),
            state=doctor.state,
            output_path=output_path
        )

        with open(output_path, 'rb') as f:
            doctor.output_video.save(f"{doctor.id}_output.mp4", File(f), save=True)

        BASE_URL = "https://api.videomaker.digielvestech.in/"
        doctor.output_video_url = f"{BASE_URL}{doctor.output_video.url}"
        doctor.save()
        logger.info(f"Video generated and saved for doctor {doctor.name}")

    except Exception as e:
        logger.error(f"Error generating video for doctor {doctor.name}: {e}")

@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
def bulk_upload_doctors(request):
    excel_file = request.FILES.get('file')
    if not excel_file:
        return Response({'error': 'No file provided.'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        df = pd.read_excel(excel_file)
        required_columns = {'name', 'clinic', 'city', 'specialization', 'state'}
        if not required_columns.issubset(df.columns):
            return Response({'error': f'Missing required columns: {required_columns - set(df.columns)}'}, status=status.HTTP_400_BAD_REQUEST)

        created, skipped, errors = 0, 0, []
        for index, row in df.iterrows():
            row_number = index + 2
            name = str(row.get('name', '')).strip()
            clinic = str(row.get('clinic', '')).strip()
            city = str(row.get('city', '')).strip()
            specialization = str(row.get('specialization', '')).strip()
            state = str(row.get('state', '')).strip()

            if not name or not clinic or not city or not specialization or not state:
                skipped += 1
                errors.append({'row': row_number, 'error': 'Required fields are missing'})
                continue

            designation = str(row.get('designation', '')).strip()
            mobile_number = str(row.get('mobile_number', '')).strip()
            whatsapp_number = str(row.get('whatsapp_number', '')).strip()
            description = str(row.get('description', '')).strip()
            image_path = str(row.get('image_url', '')).strip()
            employee = row.get('emp_id')

            image_file = None
            if image_path and os.path.exists(image_path):
                image_file = File(open(image_path, 'rb'), name=os.path.basename(image_path))

            doctor_data = {
                'name': name,
                'clinic': clinic,
                'city': city,
                'specialization': specialization,
                'state': state,
                'image': image_file,
                'designation': designation,
                'mobile_number': mobile_number,
                'whatsapp_number': whatsapp_number,
                'description': description,
                'employee': employee,
            }

            serializer = DoctorSerializer(data=doctor_data)
            if serializer.is_valid():
                try:
                    doctor = serializer.save()
                    generate_video_for_doctor(doctor)
                    created += 1
                except IntegrityError:
                    skipped += 1
                    errors.append({'row': row_number, 'error': 'Integrity error during save'})
            else:
                skipped += 1
                errors.append({'row': row_number, 'error': serializer.errors})

        return Response({'created': created, 'skipped': skipped, 'errors': errors}, status=status.HTTP_201_CREATED)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# ------------------------------------------------------------------------------
# Export/Counts
# ------------------------------------------------------------------------------

class DoctorVideoExportExcelView(APIView):
    def get(self, request):
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "Doctor Videos"
        headers = [
            "Name", "Designation", "Clinic", "City", "State", "Image URL",
            "Specialization", "Mobile Number", "WhatsApp Number", "Description", "Template Name",
            "Output Video URL", "Created At", "Employee ID", "Employee Name", "RBM Name"
        ]
        sheet.append(headers)
        doctor_videos = DoctorVideo.objects.all()
        for video in doctor_videos:
            latest_output = video.doctoroutputvideo_set.order_by('-created_at').first()
            if latest_output and latest_output.video_file:
                output_video_url = request.build_absolute_uri(latest_output.video_file.url)
                template_name = latest_output.template.name if latest_output.template else ""
            elif video.output_video:
                output_video_url = request.build_absolute_uri(video.output_video.url)
                template_name = ""
            else:
                output_video_url = ""
                template_name = ""
            rbm_name = (
                f"{video.employee.rbm.first_name} {video.employee.rbm.last_name}"
                if video.employee and getattr(video.employee, 'rbm', None) else ""
            )
            sheet.append([
                video.name, video.designation, video.clinic, video.city, video.state,
                request.build_absolute_uri(video.image.url) if video.image else "",
                video.specialization, video.mobile_number, video.whatsapp_number, video.description,
                template_name, output_video_url,
                video.created_at.strftime('%Y-%m-%d %H:%M:%S') if video.created_at else "",
                video.employee.employee_id if video.employee else "",
                f"{video.employee.first_name} {video.employee.last_name}" if video.employee else "",
                rbm_name,
            ])
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = 'attachment; filename=doctor_videos.xlsx'
        workbook.save(response)
        return response

class EmployeeExportExcelView(APIView):
    def get(self, request):
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "Employees"
        headers = ["Employee ID", "First Name", "Last Name", "Email", "Phone", "Department", "Date Joined", "User Type", "Status"]
        sheet.append(headers)
        for emp in Employee.objects.all():
            sheet.append([
                emp.employee_id, emp.first_name, emp.last_name or "", emp.email or "", emp.phone or "",
                emp.department or "", emp.date_joined.strftime('%Y-%m-%d') if emp.date_joined else "",
                emp.user_type, "Active" if emp.status else "Inactive"
            ])
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = 'attachment; filename=employees.xlsx'
        workbook.save(response)
        return response

@api_view(['GET'])
def total_employee_count(request):
    return Response({"total_employees": Employee.objects.count()}, status=status.HTTP_200_OK)

@api_view(['GET'])
def todays_active_employees(request):
    today = timezone.now().date()
    employees = Employee.objects.filter(login_history__login_time__date=today).distinct()
    count = employees.count()
    data = [{
        'employee_id': emp.employee_id,
        'name': f"{emp.first_name} {emp.last_name}",
        'email': emp.email,
        'department': emp.department,
        'user_type': emp.user_type,
    } for emp in employees]
    return Response({'date': str(today), 'active_employee_count': count, 'active_employees': data})

class TodaysActiveEmployeeExcelExport(APIView):
    def get(self, request):
        today = timezone.now().date()
        employees = Employee.objects.filter(login_history__login_time__date=today).distinct()
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "Today's Active Employees"
        headers = ["Employee ID", "First Name", "Last Name", "Email", "Phone", "Department", "Date Joined", "User Type", "Status"]
        sheet.append(headers)
        for emp in employees:
            sheet.append([
                emp.employee_id, emp.first_name, emp.last_name or "", emp.email or "", emp.phone or "",
                emp.department or "", emp.date_joined.strftime('%Y-%m-%d') if emp.date_joined else "",
                emp.user_type, "Active" if emp.status else "Inactive"
            ])
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename=active_employees_{today}.xlsx'
        workbook.save(response)
        return response

@api_view(['GET'])
def doctors_with_output_video_count(request):
    count = DoctorVideo.objects.filter(Q(output_video__isnull=False) & ~Q(output_video='')).count()
    return Response({"doctor_with_output_video_count": count}, status=status.HTTP_200_OK)

@api_view(['GET'])
def doctors_with_output_video_excel(request):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Doctor Videos"
    headers = [
        "Name", "Designation", "Clinic", "City", "State", "Image URL",
        "Specialization", "Mobile Number", "WhatsApp Number", "Description",
        "Output Video URL", "Created At", "Employee ID", "Employee Name", "RBM Name"
    ]
    sheet.append(headers)
    doctor_videos = DoctorVideo.objects.all()
    for video in doctor_videos:
        rbm_name = (
            f"{video.employee.rbm.first_name} {video.employee.rbm.last_name}"
            if video.employee and getattr(video.employee, 'rbm', None) else ""
        )
        sheet.append([
            video.name, video.designation, video.clinic, video.city, video.state,
            request.build_absolute_uri(video.image.url) if video.image else "",
            video.specialization, video.mobile_number, video.whatsapp_number, video.description,
            request.build_absolute_uri(video.output_video.url) if video.output_video else "",
            video.created_at.strftime('%Y-%m-%d %H:%M:%S') if video.created_at else "",
            video.employee.employee_id if video.employee else "",
            f"{video.employee.first_name} {video.employee.last_name}" if video.employee else "",
            rbm_name,
        ])
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename=doctor_videos.xlsx'
    workbook.save(response)
    return response

@api_view(['GET'])
def doctors_count(request):
    return Response({"doctor_count": DoctorVideo.objects.count()}, status=status.HTTP_200_OK)

# ------------------------------------------------------------------------------
# Templates (Video)
# ------------------------------------------------------------------------------

class VideoTemplateAPIView(APIView):

    def get(self, request, pk=None):
        if pk:
            template = get_object_or_404(VideoTemplates, pk=pk)
            serializer = VideoTemplatesSerializer(template)
        else:
            status_param = request.query_params.get('status')
            template_type = request.query_params.get('template_type', 'video')  # <- NEW

            templates = VideoTemplates.objects.filter(template_type=template_type)  # <- NEW

            if status_param is not None:
                try:
                    status_bool = bool(strtobool(status_param))
                    templates = templates.filter(status=status_bool)
                except ValueError:
                    return Response({"error": "Invalid status value. Use true or false."},
                                    status=status.HTTP_400_BAD_REQUEST)

            templates = templates.order_by('-created_at')
            serializer = VideoTemplatesSerializer(templates, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = VideoTemplatesSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request, pk):
        template = get_object_or_404(VideoTemplates, pk=pk)
        serializer = VideoTemplatesSerializer(template, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        template = get_object_or_404(VideoTemplates, pk=pk)
        template.delete()
        return Response({"detail": "Deleted successfully."}, status=status.HTTP_204_NO_CONTENT)

# ------------------------------------------------------------------------------
# On-demand generation (Video) with dynamic time slots
# ------------------------------------------------------------------------------

class GenerateDoctorOutputVideoView(APIView):

    def parse_time_duration(self, time_duration_str):
        if not time_duration_str or not time_duration_str.strip():
            raise ValueError("Time duration cannot be empty")
        try:
            slots = []
            for time_range in time_duration_str.strip().split(','):
                start_str, end_str = time_range.strip().split('-')
                start_time = int(start_str.strip())
                end_time = int(end_str.strip())
                if start_time >= end_time:
                    raise ValueError(f"Start time ({start_time}) must be less than end time ({end_time})")
                if start_time < 0:
                    raise ValueError(f"Start time ({start_time}) cannot be negative")
                slots.append((start_time, end_time))
            return slots
        except ValueError as e:
            if "not enough values" in str(e) or "too many values" in str(e):
                raise ValueError(
                    f"Invalid time duration format: '{time_duration_str}'. "
                    "Use '10-15' or '10-15,46-50'"
                )
            raise
        except Exception as e:
            raise ValueError(f"Error parsing time duration '{time_duration_str}': {str(e)}")

    def post(self, request):
        doctor_id = request.data.get("doctor_id")
        template_id = request.data.get("template_id")
        if not doctor_id:
            return Response({"error": "doctor_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            doctor = DoctorVideo.objects.get(id=doctor_id)
        except DoctorVideo.DoesNotExist:
            return Response({"error": "Doctor not found."}, status=status.HTTP_404_NOT_FOUND)

        if template_id:
            try:
                template = VideoTemplates.objects.get(id=template_id)
            except VideoTemplates.DoesNotExist:
                return Response({"error": "Template not found."}, status=status.HTTP_404_NOT_FOUND)
        else:
            template = VideoTemplates.objects.filter(status=True).first()
            if not template:
                return Response({"error": "No default template available."}, status=status.HTTP_400_BAD_REQUEST)

        if not doctor.image:
            return Response({"error": "Doctor does not have an image."}, status=status.HTTP_400_BAD_REQUEST)

        image_path = doctor.image.path
        random_key = uuid.uuid4().hex[:8]
        output_filename = f"{doctor.id}_{template.id}_{random_key}_output.mp4"
        output_dir = os.path.join(settings.MEDIA_ROOT, "output", str(doctor.employee.id), str(doctor.id))
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, output_filename)

        try:
            self.generate_custom_video(
                main_video_path=template.template_video.path,
                image_path=image_path,
                name=doctor.name,
                clinic=doctor.clinic,
                city=doctor.city,
                specialization_key=doctor.specialization_key,
                state=doctor.state,
                output_path=output_path,
                time_duration=template.time_duration,
                resolution=template.resolution,
                base_x=template.base_x_axis,
                base_y=template.base_y_axis,
                line_spacing=template.line_spacing,
                overlay_x=template.overlay_x,
                overlay_y=template.overlay_y,
            )
            relative_path = os.path.relpath(output_path, settings.MEDIA_ROOT)
            output_video = DoctorOutputVideo.objects.create(
                doctor=doctor,
                template=template,
                video_file=relative_path
            )
            serializer = DoctorOutputVideoSerializer(output_video)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error(f"Video generation failed: {e}")
            return Response({"error": "Video generation failed.", "details": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def generate_custom_video(
        self,
        main_video_path,
        image_path,
        name,
        clinic,
        city,
        specialization_key,
        state,
        output_path,
        time_duration="5-10,45-50",
        resolution="415x410",
        base_x="(main_w/2)-160",
        base_y="(main_h/2)-60",
        line_spacing="60",
        overlay_x="350",
        overlay_y="70"
    ):
        if not os.path.exists(main_video_path):
            raise Exception(f"Template video not found: {main_video_path}")
        if not os.path.exists(image_path):
            raise Exception(f"Doctor image not found: {image_path}")

        temp_dir = os.path.join(settings.MEDIA_ROOT, "temp")
        os.makedirs(temp_dir, exist_ok=True)

        fps = 30
        fade_duration = 3
        slots = self.parse_time_duration(time_duration)

        temp_videos = []
        for i, (start, end) in enumerate(slots):
            duration = end - start
            total_frames = duration * fps
            zoom_effect = (
                f"zoompan=z='1+0.00003*in':"
                f"x='(iw/2)-(iw/zoom/2)':"
                f"y='(ih/2)-(ih/zoom/2)':d={total_frames}:s={resolution}:fps={fps}"
            )
            fade_out_start = max(0, duration - fade_duration)
            fade_effect = f"format=rgba,fade=t=in:st=0:d={fade_duration}:alpha=1,fade=t=out:st={fade_out_start}:d={fade_duration}:alpha=1"
            vf = f"scale={resolution},{zoom_effect},{fade_effect}"
            temp_video = os.path.join(temp_dir, f"temp_image_vid_{i}.mp4")

            try:
                subprocess.run(
                    ["ffmpeg", "-loop", "1", "-i", image_path, "-vf", vf, "-t", str(duration), "-y", temp_video],
                    check=True, capture_output=True, text=True
                )
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to create temp video {i}: {e.stderr}")
                raise Exception(f"Failed to create temp video: {e.stderr}")

            temp_videos.append((temp_video, start, end))

        text_lines = [str(x or "").strip() for x in [name, specialization_key, clinic, city, state]]

# Select a font present on the system/container
        font_paths = [
            os.path.join(settings.BASE_DIR, "fonts", "RobotoSlab-Medium.ttf"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",     # Linux
            "/System/Library/Fonts/Arial.ttf",                     # macOS
            r"C:\Windows\Fonts\arial.ttf",                         # Windows (common)
            r"C:\Windows\Fonts\ARIAL.TTF",                         # Windows (fallback)
            "arial.ttf",
        ]

        font = None
        for fp in font_paths:
            if os.path.exists(fp):
                font = fp  # found a real path
                break
        if not font:
            font = "Arial"  # family name for drawtext `font=`

        # Do we have a file path or a family name?
        # Normalize Windows paths for ffmpeg drawtext (forward slashes + escape ':' in drive letters)
        if isinstance(font, str) and (os.path.isabs(font) or font.lower().endswith(".ttf")):
            if os.name == "nt":
                font = font.replace("\\", "/").replace(":", r"\:")
            font_is_path = True
        else:
            font_is_path = False



        text_filters = []
        for start, end in slots:
            alpha_expr = f"if(lt(t\\,{start}+3),(t-{start})/3,if(lt(t\\,{end}-3),1,({end}-t)/3))"
            for j, text in enumerate(text_lines):
                if not text:
                    continue
                safe_text = _ff_esc(text)
                x_pos = f"{base_x}"
                y_pos = f"{base_y} + {j}*{line_spacing}"
                if font_is_path:
                    font_part = f"fontfile='{font}':"
                else:
                    font_part = f"font='{font}':"

                drawtext = (
                    f"drawtext=text='{safe_text}':{font_part}fontcolor=black:fontsize=40:"
                    f"x={x_pos}:y={y_pos}:enable='between(t,{start},{end})':alpha='{alpha_expr}'"
                )
                text_filters.append(drawtext)


        ox = _num_or_expr(overlay_x, "0")
        oy = _num_or_expr(overlay_y, "0")
        overlay_x1 = f"(main_w-overlay_w)/2-({ox})"
        overlay_y1 = f"(main_h-overlay_h)/2+({oy})"


        overlay_filters = []
        for i, (start, end) in enumerate(slots):
            input_label = "[0:v]" if i == 0 else f"[v{i}]"
            output_label = f"[v{i+1}]"
            overlay_filters.append(
                f"{input_label}[{i+1}:v]overlay=x={overlay_x1}:y={overlay_y1}:enable='between(t,{start},{end})'{output_label}"
            )

        final_input = f"[v{len(slots)}]"
        filter_complex = f"{';'.join(overlay_filters)};{final_input}{','.join(text_filters)}[v]"

        cmd = ["ffmpeg", "-i", main_video_path]
        for temp_video, _, _ in temp_videos:
            cmd.extend(["-i", temp_video])
        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "0:a?",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-movflags", "+faststart",
            "-y", output_path
        ])


        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Final FFmpeg failed: {e.stderr}")
            raise Exception(f"Video generation failed: {e.stderr}")
        finally:
            for temp_video, _, _ in temp_videos:
                if os.path.exists(temp_video):
                    os.remove(temp_video)

    def get(self, request):
        doctor_id = request.query_params.get("doctor_id")
        employee_id = request.query_params.get("employee_id")
        videos = DoctorOutputVideo.objects.all().order_by('-id')
        if doctor_id:
            videos = videos.filter(doctor_id=doctor_id)
        if employee_id:
            videos = videos.filter(doctor__employee__employee_id=employee_id)
        paginator = Pagination_class()
        paginated_videos = paginator.paginate_queryset(videos, request)
        serializer = DoctorOutputVideoSerializer(paginated_videos, many=True)
        return paginator.get_paginated_response(serializer.data)

# ------------------------------------------------------------------------------
# Employee updates from Excel
# ------------------------------------------------------------------------------

@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
def update_employees_from_excel(request):
    excel_file = request.FILES.get('file')
    if not excel_file:
        return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        df = pd.read_excel(excel_file)
        updated, not_found = 0, 0
        for _, row in df.iterrows():
            employee_id = str(row['id']).strip()
            department = str(row['department']).strip()
            city = str(row['city']).strip().title()
            try:
                employee = Employee.objects.get(employee_id=employee_id)
                employee.department = department
                employee.city = city
                employee.save()
                updated += 1
            except Employee.DoesNotExist:
                not_found += 1
        return Response({'status': 'success', 'updated': updated, 'not_found': not_found})
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class TemplateWiseVideoCountView(APIView):
    def get(self, request):
        template_counts = DoctorOutputVideo.objects.values("template__id", "template__name").annotate(video_count=Count("id")).order_by("-video_count")
        data = [{
            "template_id": item["template__id"],
            "template_name": item["template__name"],
            "video_count": item["video_count"]
        } for item in template_counts if item["template__id"] is not None]
        return Response(data, status=status.HTTP_200_OK)

# ------------------------------------------------------------------------------
# Image Templates & Image Generation
# ------------------------------------------------------------------------------

class ImageTemplateAPIView(APIView):
    """Handle image templates separately from video templates"""

    def get(self, request, pk=None):
        if pk:
            template = get_object_or_404(VideoTemplates, pk=pk, template_type='image')
            serializer = ImageTemplateSerializer(template, context={'request': request})
        else:
            status_param = request.query_params.get('status')
            templates = VideoTemplates.objects.filter(template_type='image')
            if status_param is not None:
                try:
                    status_bool = bool(strtobool(status_param))
                    templates = templates.filter(status=status_bool)
                except ValueError:
                    return Response({"error": "Invalid status value. Use true or false."}, status=status.HTTP_400_BAD_REQUEST)
            templates = templates.order_by('-created_at')
            serializer = ImageTemplateSerializer(templates, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = ImageTemplateSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request, pk):
        template = get_object_or_404(VideoTemplates, pk=pk, template_type='image')
        serializer = ImageTemplateSerializer(template, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        template = get_object_or_404(VideoTemplates, pk=pk, template_type='image')
        template.delete()
        return Response({"detail": "Template deleted successfully."}, status=status.HTTP_204_NO_CONTENT)

class GenerateImageContentView(APIView):
    """Generate image with text overlay - DoctorVideo only"""

    def post(self, request):
        template_id = request.data.get("template_id")
        doctor_id = request.data.get("doctor_id")
        mobile = request.data.get("mobile")
        name = request.data.get("name")
        content_data = request.data.get("content_data", {})
        selected_brand_ids = request.data.get("selected_brands", [])

        if not template_id:
            return Response({"error": "template_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        if not doctor_id and not (mobile and name):
            return Response({"error": "Either doctor_id OR (mobile + name) is required."}, status=status.HTTP_400_BAD_REQUEST)
        
        if not isinstance(selected_brand_ids, list) or not all(isinstance(bid, int) for bid in selected_brand_ids):
            return Response({"error": "selected_brands must be a list of brand IDs."}, status=status.HTTP_400_BAD_REQUEST)

        if len(selected_brand_ids) > 6:
            return Response({"error": "You can select up to 6 brands only."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            template = VideoTemplates.objects.get(id=template_id, template_type='image')
        except VideoTemplates.DoesNotExist:
            return Response({"error": "Image template not found."}, status=status.HTTP_404_NOT_FOUND)

         # Associate selected brands with the template
        if selected_brand_ids:
            brands = Brand.objects.filter(id__in=selected_brand_ids)
            template.selected_brands.set(brands)
            template.save()

        # Scenario 1: Existing DoctorVideo by ID
        is_new_doctor = False
        if doctor_id:
            try:
                doctor_video = DoctorVideo.objects.get(id=doctor_id)
            except DoctorVideo.DoesNotExist:
                return Response({"error": "Doctor not found."}, status=status.HTTP_404_NOT_FOUND)
        else:
            # Scenario 2: Find/create by mobile
            doctor_video = DoctorVideo.objects.filter(mobile_number=mobile).first()
            if not doctor_video:
                # Need an employee
                try:
                    employee_id = request.data.get("employee_id")
                    if employee_id:
                        employee = Employee.objects.get(employee_id=employee_id)
                    else:
                        employee = Employee.objects.first()
                        if not employee:
                            return Response({"error": "No employees found in system."}, status=status.HTTP_404_NOT_FOUND)
                except Employee.DoesNotExist:
                    return Response({"error": f"Employee {employee_id} not found."}, status=status.HTTP_404_NOT_FOUND)

                clinic = content_data.get("doctor_clinic") or request.data.get("clinic", "Unknown Clinic")
                city = content_data.get("doctor_city") or request.data.get("city", "Unknown City")
                specialization = content_data.get("doctor_specialization") or request.data.get("specialization", "General Medicine")
                state = content_data.get("doctor_state") or request.data.get("state", "Unknown State")

                doctor_video = DoctorVideo.objects.create(
                    name=name,
                    clinic=clinic,
                    city=city,
                    specialization=specialization,
                    specialization_key=specialization,
                    state=state,
                    mobile_number=mobile,
                    whatsapp_number=mobile,
                    description=request.data.get("description", ""),
                    designation=request.data.get("designation", ""),
                    employee=employee
                )
                uploaded_image = request.FILES.get('doctor_image')
                if uploaded_image:
                    doctor_video.image = uploaded_image
                    doctor_video.save()
                is_new_doctor = True

        if not template.template_image or not template.template_image.path:
            return Response({"error": "Template does not have an image file."}, status=status.HTTP_400_BAD_REQUEST)

        # Verify template image file exists
        if not os.path.exists(template.template_image.path):
            return Response({"error": "Template image file not found."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            output_path = self.generate_image_with_text(template, content_data, doctor_video)
            image_content = ImageContent.objects.create(
                template=template,
                doctor=doctor_video,
                content_data=content_data
            )
            with open(output_path, 'rb') as f:
                image_content.output_image.save(f"generated_{image_content.id}.png", File(f), save=True)
            os.remove(output_path)

            serializer = ImageContentSerializer(image_content, context={'request': request})
            resp = serializer.data
            resp['doctor_info'] = {
                'id': doctor_video.id,
                'name': doctor_video.name,
                'clinic': doctor_video.clinic,
                'mobile': doctor_video.mobile_number,
                'has_image': bool(doctor_video.image),
                'is_new_doctor': is_new_doctor
            }
            resp['selected_brands'] = [
                {'id': b.id, 'name': b.name}
                for b in template.selected_brands.all()
            ]

            return Response(resp, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error(f"Image generation failed: {e}")
            logger.error(f"Template ID: {template.id}, Template has image: {bool(template.template_image)}")
            if template.template_image:
                logger.error(f"Template image path: {template.template_image.path}")
            return Response({"error": "Image generation failed.", "details": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def generate_image_with_text(self, template, content_data, doctor):
        logger.info(f"Starting image generation for template {template.id}")
        logger.info(f"Template image field: {template.template_image}")
        logger.info(f"Template image path: {template.template_image.path if template.template_image else 'None'}")
        
        if not template.template_image or not template.template_image.path:
            raise Exception("Template image path is None or empty")
        
        if not os.path.exists(template.template_image.path):
            raise Exception(f"Template image file does not exist: {template.template_image.path}")
        
        logger.info("Opening template image...")
        template_image = Image.open(template.template_image.path)
        logger.info("Creating ImageDraw...")
        draw = ImageDraw.Draw(template_image)
        
        logger.info("Getting text positions...")
        positions = template.text_positions or {}
        logger.info(f"Text positions: {positions}")

        positions = template.text_positions or {}
        # Font mapping for PIL
        FONT_MAP = {
            'Arial': 'arial.ttf',
            'Times New Roman': 'times.ttf',
            'Helvetica': 'arial.ttf',
            'Georgia': 'georgia.ttf',
            'Verdana': 'verdana.ttf',
            'Impact': 'impact.ttf',
            'Comic Sans MS': 'comic.ttf'
        }

        def get_font(font_family, font_size):
            font_file = FONT_MAP.get(font_family, 'arial.ttf')
            try:
                return ImageFont.truetype(font_file, font_size)
            except:  # noqa: E722
                try:
                    return ImageFont.truetype("arial.ttf", font_size)
                except:  # noqa: E722
                    return ImageFont.load_default()

        all_text_data = {
            'name': content_data.get('doctor_name', doctor.name),
            'clinic': content_data.get('doctor_clinic', doctor.clinic),
            'city': content_data.get('doctor_city', doctor.city),
            'specialization': content_data.get('doctor_specialization', doctor.specialization),
            'state': content_data.get('doctor_state', doctor.state),
            'mobile': doctor.mobile_number,
            'customText': template.custom_text or '',
        }

        # Draw each mapped field
        for field_name, text_value in all_text_data.items():
            if field_name in positions and text_value:
                pos = positions[field_name]
                font_size = int(pos.get('fontSize', 40))
                color = pos.get('color', 'black')
                font_weight = pos.get('fontWeight', 'normal')
                font_family = pos.get('fontFamily', 'Arial')

                styled_font = get_font(font_family, font_size)
                if font_weight == 'bold':
                    try:
                        bold_font_file = FONT_MAP.get(font_family, 'arial.ttf').replace('.ttf', 'bd.ttf')
                        styled_font = ImageFont.truetype(bold_font_file, font_size)
                    except:  # noqa: E722
                        styled_font = get_font(font_family, font_size)

                text_shadow = pos.get('textShadow', 'none')
                if text_shadow != 'none':
                    shadow_info = parse_css_shadow(text_shadow)
                    if shadow_info:
                        draw.text(
                            (int(pos['x']) + shadow_info['offset_x'], int(pos['y']) + shadow_info['offset_y']),
                            str(text_value), fill=shadow_info['color'], font=styled_font
                        )

                draw.text((int(pos['x']), int(pos['y'])), str(text_value), fill=color, font=styled_font)

        # Optional doctor image overlay
        image_settings = None
        if content_data and 'imageSettings' in content_data:
            image_settings = content_data['imageSettings']
        elif template.text_positions and 'imageSettings' in template.text_positions:
            image_settings = template.text_positions['imageSettings']

        if image_settings and image_settings.get('enabled', False):
            try:
                logger.info(f"Doctor image enabled. Doctor: {doctor.name}")
                logger.info(f"Doctor image field: {doctor.image}")
                logger.info(f"Doctor image path: {doctor.image.path if doctor.image else 'None'}")
                
                img_x = int(image_settings.get('x', 400))
                img_y = int(image_settings.get('y', 50))
                img_width = int(image_settings.get('width', 150))
                img_height = int(image_settings.get('height', 150))
                img_fit = image_settings.get('fit', 'cover')
                border_radius = int(image_settings.get('borderRadius', 0))
                opacity = int(image_settings.get('opacity', 100))

                if doctor.image and doctor.image.path and os.path.exists(doctor.image.path):
                    doctor_img = Image.open(doctor.image.path)
                    if img_fit == 'cover':
                        doctor_img = doctor_img.resize((img_width, img_height), Image.Resampling.LANCZOS)
                    elif img_fit == 'contain':
                        doctor_img.thumbnail((img_width, img_height), Image.Resampling.LANCZOS)
                    elif img_fit == 'stretch':
                        doctor_img = doctor_img.resize((img_width, img_height), Image.Resampling.LANCZOS)
                else:
                    doctor_img = Image.new('RGB', (img_width, img_height), color='#4A90E2')
                    draw_placeholder = ImageDraw.Draw(doctor_img)
                    fsz = max(20, min(img_width, img_height) // 4)
                    try:
                        placeholder_font = ImageFont.truetype("arial.ttf", fsz)
                    except:  # noqa: E722
                        placeholder_font = ImageFont.load_default()
                    draw_placeholder.text((img_width//2, img_height//2), "DR", fill='white', font=placeholder_font, anchor="mm")

                if border_radius > 0:
                    mask = Image.new('L', (doctor_img.width, doctor_img.height), 0)
                    mask_draw = ImageDraw.Draw(mask)
                    actual_radius = min(doctor_img.width, doctor_img.height) * border_radius // 200
                    mask_draw.rounded_rectangle([(0, 0), (doctor_img.width, doctor_img.height)], radius=actual_radius, fill=255)
                    if doctor_img.mode != 'RGBA':
                        doctor_img = doctor_img.convert('RGBA')
                    doctor_img.putalpha(mask)

                if opacity < 100:
                    if doctor_img.mode != 'RGBA':
                        doctor_img = doctor_img.convert('RGBA')
                    alpha = doctor_img.split()[-1]
                    alpha = alpha.point(lambda p: int(p * opacity / 100))
                    doctor_img.putalpha(alpha)

                if template_image.mode != 'RGBA':
                    template_image = template_image.convert('RGBA')
                if doctor_img.mode == 'RGBA':
                    template_image.paste(doctor_img, (img_x, img_y), doctor_img)
                else:
                    template_image.paste(doctor_img, (img_x, img_y))
            except Exception as e:
                logger.error(f"Error compositing doctor image: {e}")

        #output_dir = os.path.join(settings.MEDIA_ROOT, "temp")

        output_dir = os.path.join(settings.MEDIA_ROOT, "temp")

        # Render brands using TemplateBrandPosition model
        # Render brands using TemplateBrandPosition model
        # DEBUG: Check what templates and brands exist
        logger.info(f"Template ID: {template.id}, Template name: {template.name}")
        all_brand_positions = TemplateBrandPosition.objects.all()
        logger.info(f"Total brand positions in database: {all_brand_positions.count()}")
        for bp in all_brand_positions:
            logger.info(f"  - Template {bp.template.id}: Brand {bp.brand.name} at ({bp.x}, {bp.y})")

        # Render brands using TemplateBrandPosition model
        brand_positions = TemplateBrandPosition.objects.filter(template=template).select_related('brand')
        logger.info(f"Found {brand_positions.count()} brand positions for template {template.id}")
        
        for brand_pos in brand_positions:
            brand = brand_pos.brand
            logger.info(f"Processing brand: {brand.name}, image path: {brand.brand_image.path if brand.brand_image else 'None'}")
            
            if brand.brand_image:
                brand_image_path = brand.brand_image.path
                logger.info(f"Brand image full path: {brand_image_path}")
                
                if os.path.exists(brand_image_path):
                    try:
                        # Open and process brand image
                        brand_img = Image.open(brand_image_path)
                        
                        # Convert to RGBA if needed
                        if brand_img.mode != 'RGBA':
                            brand_img = brand_img.convert('RGBA')
                        
                        # Resize brand image to specified dimensions
                        brand_img = brand_img.resize((brand_pos.width, brand_pos.height), Image.Resampling.LANCZOS)
                        
                        # Ensure template image is in RGBA mode for proper alpha blending
                        if template_image.mode != 'RGBA':
                            template_image = template_image.convert('RGBA')

                        # Paste brand image onto template
                        template_image.paste(brand_img, (brand_pos.x, brand_pos.y), brand_img)
                        logger.info(f"Successfully rendered brand {brand.name} at ({brand_pos.x}, {brand_pos.y}) with size {brand_pos.width}x{brand_pos.height}")
                        
                    except Exception as e:
                        logger.error(f"Failed to render brand {brand.name}: {e}")
                        import traceback
                        logger.error(f"Brand rendering traceback: {traceback.format_exc()}")
                else:
                    logger.warning(f"Brand image file does not exist: {brand_image_path}")
            else:
                logger.warning(f"Brand {brand.name} has no brand_image field set")

        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"temp_image_{uuid.uuid4().hex}.png")
        template_image.save(output_path)
        return output_path


class ImageContentListView(APIView):
    """List generated image contents with pagination"""
    def get(self, request):
        doctor_id = request.GET.get('doctor_id')
        template_id = request.GET.get('template_id')
        contents = ImageContent.objects.all()
        if doctor_id:
            try:
                doctor = DoctorVideo.objects.get(id=doctor_id)
                contents = contents.filter(doctor=doctor)
            except DoctorVideo.DoesNotExist:
                return Response({"error": "Doctor not found."}, status=status.HTTP_404_NOT_FOUND)
        if template_id:
            contents = contents.filter(template_id=template_id)
        paginator = Pagination_class()
        page = paginator.paginate_queryset(contents, request)
        serializer = ImageContentSerializer(page, many=True, context={'request': request})
        return paginator.get_paginated_response(serializer.data)

class DoctorSearchView(APIView):
    """Search doctor by mobile number or name"""
    def get(self, request):
        mobile = request.GET.get('mobile')
        if not mobile:
            return Response({"error": "mobile parameter required."}, status=status.HTTP_400_BAD_REQUEST)
        doctor_video = DoctorVideo.objects.filter(mobile_number=mobile).first()
        if doctor_video:
            return Response({
                "found": True,
                "doctor": {
                    "id": doctor_video.id, "name": doctor_video.name, "clinic": doctor_video.clinic,
                    "city": doctor_video.city, "mobile": doctor_video.mobile_number,
                    "specialization": doctor_video.specialization, "state": doctor_video.state,
                    "model": "DoctorVideo"
                }
            })
        doctor = Doctor.objects.filter(mobile_number=mobile).first()
        if doctor:
            return Response({
                "found": True,
                "doctor": {
                    "id": doctor.id, "name": doctor.name, "clinic": doctor.clinic,
                    "city": doctor.city, "mobile": doctor.mobile_number,
                    "specialization": doctor.specialization, "model": "Doctor"
                },
                "note": "Doctor found in main database. Will be converted to DoctorVideo when image is generated."
            })
        return Response({"found": False})

@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
def AddEmployeeTemplates(request, template_type='video'):
    """Handle both video and image template creation"""
    try:
        data = request.data.copy()
        data['template_type'] = template_type

        if template_type == 'image':
            text_positions = data.get('text_positions', '{}')
            image_settings = data.get('imageSettings', '{}')
            if isinstance(text_positions, str):
                text_positions = json.loads(text_positions)
            if isinstance(image_settings, str):
                image_settings = json.loads(image_settings)
            combined_positions = text_positions.copy() if text_positions else {}
            combined_positions['imageSettings'] = image_settings
            data['text_positions'] = json.dumps(combined_positions)

        serializer = ImageTemplateSerializer(data=data, context={'request': request}) if template_type == 'image' \
            else VideoTemplatesSerializer(data=data)

        if serializer.is_valid():
            template = serializer.save()
            return Response({
                'id': template.id,
                'message': f'{template_type.title()} template created successfully',
                'status': template.status
            }, status=status.HTTP_201_CREATED)
        else:
            return Response({'error': 'Validation failed', 'details': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        return Response({'error': 'Template creation failed', 'details': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
def getFilteredVideoTemplates(request):
    """Get filtered templates by status & type"""
    status_param = request.GET.get('status', 'true')
    template_type = request.GET.get('template_type', 'video')
    try:
        status_bool = bool(strtobool(status_param))
        templates = VideoTemplates.objects.filter(status=status_bool, template_type=template_type).order_by('-created_at')
        serializer = ImageTemplateSerializer(templates, many=True, context={'request': request}) if template_type == 'image' \
            else VideoTemplatesSerializer(templates, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# ------------------------------------------------------------------------------
# Doctor Update/Delete (with permission checks)
# ------------------------------------------------------------------------------

class DoctorUpdateDeleteView(APIView):
    permission_classes = []  # Explicitly override global auth
    authentication_classes = []

    def get_doctor(self, doctor_id, employee_id):
        try:
            doctor = DoctorVideo.objects.get(id=doctor_id)
            try:
                current_employee = Employee.objects.get(employee_id=employee_id)
            except Employee.DoesNotExist:
                raise PermissionError("Employee not found")
            if current_employee.user_type != 'Admin' and doctor.employee != current_employee:
                raise PermissionError("You can only edit your own doctors")
            return doctor
        except DoctorVideo.DoesNotExist:
            raise Http404("Doctor not found")

    def patch(self, request, doctor_id):
        try:
            employee_id = request.data.get('employee_id')
            if not employee_id:
                return Response({'error': 'employee_id is required'}, status=status.HTTP_400_BAD_REQUEST)
            doctor = self.get_doctor(doctor_id, employee_id)
            serializer = DoctorVideoSerializer(doctor, data=request.data, partial=True)
            if serializer.is_valid():
                updated_doctor = serializer.save()
                return Response({'status': 'success', 'message': 'Doctor updated successfully', 'data': DoctorVideoSerializer(updated_doctor).data})
            else:
                return Response({'status': 'error', 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionError as e:
            return Response({'error': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request, doctor_id):
        try:
            employee_id = request.query_params.get('employee_id')
            if not employee_id:
                return Response({'error': 'employee_id is required'}, status=status.HTTP_400_BAD_REQUEST)
            doctor = self.get_doctor(doctor_id, employee_id)
            doctor_name = doctor.name
            DoctorOutputVideo.objects.filter(doctor=doctor).delete()
            ImageContent.objects.filter(doctor=doctor).delete()
            doctor.delete()
            return Response({'status': 'success', 'message': f'Doctor {doctor_name} and all associated content deleted successfully'})
        except PermissionError as e:
            return Response({'error': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# ------------------------------------------------------------------------------
# Regenerate Content (video/image) with permissions
# ------------------------------------------------------------------------------

class RegenerateContentView(APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        doctor_id = request.data.get('doctor_id')
        template_id = request.data.get('template_id')
        content_type = request.data.get('content_type')  # 'video' or 'image'

        if not all([doctor_id, template_id, content_type]):
            return Response({'error': 'doctor_id, template_id, and content_type are required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            doctor = DoctorVideo.objects.get(id=doctor_id)
            employee_id = request.data.get('employee_id')
            if not employee_id:
                return Response({'error': 'employee_id is required'}, status=status.HTTP_400_BAD_REQUEST)
            try:
                current_employee = Employee.objects.get(employee_id=employee_id)
            except Employee.DoesNotExist:
                return Response({'error': 'Employee not found'}, status=status.HTTP_404_NOT_FOUND)
            if current_employee.user_type != 'Admin' and doctor.employee != current_employee:
                return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

            template = VideoTemplates.objects.get(id=template_id)

            if content_type == 'video':
                return self.regenerate_video(doctor, template)
            elif content_type == 'image':
                return self.regenerate_image(doctor, template, request.data.get('content_data', {}))
            else:
                return Response({'error': 'Invalid content_type'}, status=status.HTTP_400_BAD_REQUEST)

        except DoctorVideo.DoesNotExist:
            return Response({'error': 'Doctor not found'}, status=status.HTTP_404_NOT_FOUND)
        except VideoTemplates.DoesNotExist:
            return Response({'error': 'Template not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def regenerate_video(self, doctor, template):
        if not doctor.image:
            return Response({'error': 'Doctor has no image for video generation'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            output_filename = f"{doctor.id}_{template.id}_{uuid.uuid4().hex[:8]}_output.mp4"
            output_dir = os.path.join(settings.MEDIA_ROOT, "output", str(doctor.employee.id), str(doctor.id))
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, output_filename)

            # Reuse sync compose (you can swap to Celery if preferred)
            VideoGenViewSet().generate_custom_video(
                main_video_path=template.template_video.path,
                image_path=doctor.image.path,
                name=doctor.name,
                clinic=doctor.clinic,
                city=doctor.city,
                specialization_key=doctor.specialization_key,
                state=doctor.state,
                output_path=output_path,
                time_duration=template.time_duration,
                resolution=template.resolution,
                base_x=template.base_x_axis,
                base_y=template.base_y_axis,
                line_spacing=template.line_spacing,
                overlay_x=template.overlay_x,
                overlay_y=template.overlay_y,
            )

            relative_path = os.path.relpath(output_path, settings.MEDIA_ROOT)
            output_video = DoctorOutputVideo.objects.create(
                doctor=doctor,
                template=template,
                video_file=relative_path
            )
            return Response({'status': 'success', 'message': 'Video regenerated successfully', 'data': DoctorOutputVideoSerializer(output_video).data})
        except Exception as e:
            return Response({'error': f'Video generation failed: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def regenerate_image(self, doctor, template, content_data):
        try:
            image_gen = GenerateImageContentView()
            output_path = image_gen.generate_image_with_text(template, content_data, doctor)
            image_content = ImageContent.objects.create(template=template, doctor=doctor, content_data=content_data)
            with open(output_path, 'rb') as f:
                image_content.output_image.save(f"regenerated_{image_content.id}.png", File(f), save=True)
            os.remove(output_path)
            return Response({'status': 'success', 'message': 'Image regenerated successfully', 'data': ImageContentSerializer(image_content).data})
        except Exception as e:
            return Response({'error': f'Image generation failed: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# ------------------------------------------------------------------------------
# Delete specific content
# ------------------------------------------------------------------------------

class DeleteContentView(APIView):
    permission_classes = []
    authentication_classes = []

    def delete(self, request, content_type, content_id):
        try:
            if content_type == 'video':
                content = DoctorOutputVideo.objects.get(id=content_id)
                doctor = content.doctor
            elif content_type == 'image':
                content = ImageContent.objects.get(id=content_id)
                doctor = content.doctor
            else:
                return Response({'error': 'Invalid content type'}, status=status.HTTP_400_BAD_REQUEST)

            employee_id = request.query_params.get('employee_id')
            if not employee_id:
                return Response({'error': 'employee_id is required'}, status=status.HTTP_400_BAD_REQUEST)
            try:
                current_employee = Employee.objects.get(employee_id=employee_id)
            except Employee.DoesNotExist:
                return Response({'error': 'Employee not found'}, status=status.HTTP_404_NOT_FOUND)
            if current_employee.user_type != 'Admin' and doctor.employee != current_employee:
                return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

            content.delete()
            return Response({'status': 'success', 'message': f'{content_type.title()} deleted successfully'})
        except (DoctorOutputVideo.DoesNotExist, ImageContent.DoesNotExist):
            return Response({'error': 'Content not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class BrandListAPIView(generics.ListAPIView):
    queryset = Brand.objects.all().order_by('-uploaded_at')
    serializer_class = BrandSerializer

class TemplateBrandPositionCreateView(APIView):
    def post(self, request):
        serializer = TemplateBrandPositionSerializer(data=request.data)
        if serializer.is_valid():
            # Enforce uniqueness manually if needed
            obj, created = TemplateBrandPosition.objects.update_or_create(
                template=serializer.validated_data['template'],
                brand=serializer.validated_data['brand'],
                defaults={
                    'x': serializer.validated_data['x'],
                    'y': serializer.validated_data['y'],
                    'width': serializer.validated_data['width'],
                    'height': serializer.validated_data['height'],
                }
            )
            return Response({
                "status": "updated" if not created else "created",
                "id": obj.id
            }, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
