from celery import shared_task
import logging
import os
import json
import uuid
from PIL import Image, ImageDraw, ImageFont
from django.core.files import File
from django.conf import settings

logger = logging.getLogger(__name__)

# Ensure Django is configured
import django
if not django.apps.apps.ready:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'employee_project.settings_local')
    django.setup()

# Import models after Django setup
from .models import VideoTemplates, DoctorVideo, ImageContent, Brand

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
    except:
        pass
    return {'offset_x': 2, 'offset_y': 2, 'color': (128, 128, 128)}

@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def generate_image_async(self, template_id, doctor_id, content_data, selected_brand_ids=None):
    """Generate image in background with doctor data and brands"""
    logger.info(f"Starting async image generation for template {template_id}, doctor {doctor_id}")
    
    try:
        # Get template and doctor
        template = VideoTemplates.objects.get(id=template_id, template_type='image')
        doctor = DoctorVideo.objects.get(id=doctor_id)
        
        logger.info(f"Processing doctor: {doctor.name}")
        logger.info(f"Using template: {template.name}")
        
        # Generate the image using the existing function logic
        output_path = generate_image_with_text(
            template=template,
            doctor=doctor,
            content_data=content_data,
            selected_brand_ids=selected_brand_ids or []
        )
        
        # Create database record
        image_content = ImageContent.objects.create(
            template=template,
            doctor=doctor,
            content_data=content_data
        )
        
        # Save the generated image
        with open(output_path, 'rb') as f:
            image_content.output_image.save(
                f"generated_{image_content.id}.png", 
                File(f), 
                save=True
            )
        
        # Clean up temp file
        os.remove(output_path)
        
        result = {
            "image_id": image_content.id,
            "output_image_url": image_content.output_image.url,
            "doctor_name": doctor.name,
            "status": "completed"
        }
        
        logger.info(f"Successfully completed image generation for doctor {doctor.name}")
        return result
        
    except Exception as e:
        logger.error(f"Image generation failed: {e}", exc_info=True)
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=60, exc=e)
        raise

def generate_image_with_text(template, content_data, doctor, selected_brand_ids=None):
    logger.info(f"Starting image generation for template {template.id}")
    
    if not template.template_image or not template.template_image.path:
        raise Exception("Template image path is None or empty")
    
    if not os.path.exists(template.template_image.path):
        raise Exception(f"Template image file does not exist: {template.template_image.path}")
    
    # Memory-efficient image processing with explicit cleanup
    template_image = None
    draw = None
    brand_images = []  # Track all opened images for cleanup
    
    try:
        template_image = Image.open(template.template_image.path)
        
        # Limit image size to prevent memory issues - MOVE THIS UP
        max_size = (2048, 2048)
        if template_image.size[0] > max_size[0] or template_image.size[1] > max_size[1]:
            template_image.thumbnail(max_size, Image.Resampling.LANCZOS)
            
        # Convert to RGB if needed to reduce memory
        if template_image.mode not in ('RGB', 'RGBA'):
            template_image = template_image.convert('RGB')
        
        # Limit image size to prevent memory issues
        max_size = (2048, 2048)
        if template_image.size[0] > max_size[0] or template_image.size[1] > max_size[1]:
            template_image.thumbnail(max_size, Image.Resampling.LANCZOS)
        
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
            'Comic Sans MS': 'comic.ttf',
            'Dancing Script': 'DancingScript-Regular.ttf',
            'Great Vibes': 'GreatVibes-Regular.ttf',
            'Pacifico': 'Pacifico-Regular.ttf',
            'Allura': 'Allura-Regular.ttf',
            'Alex Brush': 'AlexBrush-Regular.ttf'
        }

        def get_font(font_family, font_size, font_weight='normal', font_style='normal'):
            base_font = FONT_MAP.get(font_family, 'arial.ttf')
            
            # For cursive fonts, use full path
            if font_family in ['Dancing Script', 'Great Vibes', 'Pacifico', 'Allura', 'Alex Brush']:
                font_path = os.path.join(settings.BASE_DIR, "fonts", base_font)
            else:
                font_path = base_font
            
            # Handle font weight (bold) - only for non-cursive fonts
            if font_weight == 'bold' and font_family not in ['Dancing Script', 'Great Vibes', 'Pacifico', 'Allura', 'Alex Brush']:
                bold_font = font_path.replace('.ttf', 'bd.ttf')
                try:
                    font = ImageFont.truetype(bold_font, font_size)
                except:
                    try:
                        font = ImageFont.truetype(font_path, font_size)
                    except:
                        font = ImageFont.load_default()
            else:
                try:
                    font = ImageFont.truetype(font_path, font_size)
                except:
                    try:
                        font = ImageFont.truetype("arial.ttf", font_size)
                    except:
                        font = ImageFont.load_default()
            
            return font
        ##
        # Combine city and state with comma if both exist
        city_state = []
        if content_data.get('doctor_city', doctor.city):
            city_state.append(content_data.get('doctor_city', doctor.city))
        if content_data.get('doctor_state', doctor.state):
            city_state.append(content_data.get('doctor_state', doctor.state))
        city_state_combined = ', '.join(city_state)

        all_text_data = {
            'name': content_data.get('doctor_name', doctor.name),
            'clinic': content_data.get('doctor_clinic', doctor.clinic),
            'city': city_state_combined,  # Combined city, state
            'specialization': content_data.get('doctor_specialization', doctor.specialization),
            'mobile': doctor.mobile_number,
            'customText': template.custom_text or '',
        }

        # DOCTOR FIELDS RESPONSIVE CENTER ALIGNMENT (removed 'state' since it's now combined with city)
        doctor_fields = ['name', 'specialization', 'clinic', 'city']
        doctor_text_data = {field: all_text_data[field] for field in doctor_fields if field in all_text_data and all_text_data[field] and field in positions}

        if doctor_text_data:
            print(f"Processing doctor fields for center alignment: {list(doctor_text_data.keys())}")
            
            # Calculate text widths for center alignment
            field_widths = {}
            field_fonts = {}
            
            for field_name, text_value in doctor_text_data.items():
                pos = positions[field_name]
                font_size = int(pos.get('fontSize', 40))
                font_weight = pos.get('fontWeight', 'normal')
                font_family = pos.get('fontFamily', 'Arial')
                font_style = pos.get('fontStyle', 'normal')
                
                styled_font = get_font(font_family, font_size, font_weight, font_style)
                field_fonts[field_name] = styled_font
                
                # Calculate text width using textbbox
                bbox = draw.textbbox((0, 0), str(text_value), font=styled_font)
                text_width = bbox[2] - bbox[0]
                field_widths[field_name] = text_width
                print(f"Field {field_name}: '{text_value}' = {text_width}px wide")
            
            # Find the widest text to base centering on
            max_width = max(field_widths.values())
            widest_field = max(field_widths, key=field_widths.get)
            print(f"Widest field: {widest_field} ({max_width}px)")
            
            # Get base position from widest field
            # Calculate the visual center point of the template
            template_center_x = template_image.width // 2

            # Calculate center-aligned positions for all doctor fields
            for field_name, text_value in doctor_text_data.items():
                pos = positions[field_name]
                field_width = field_widths[field_name]
                styled_font = field_fonts[field_name]
                
                # Center each field based on template center, not relative to other fields
                centered_x = template_center_x - (field_width // 2)
                y_pos = int(pos['y'])  # Keep original Y position                
                print(f"Rendering {field_name} at centered position ({centered_x}, {y_pos})")
                
                # Apply styling
                color = pos.get('color', 'black')
                font_style = pos.get('fontStyle', 'normal')
                
                # Text shadow
                text_shadow = pos.get('textShadow', 'none')
                if text_shadow != 'none':
                    shadow_info = parse_css_shadow(text_shadow)
                    if shadow_info:
                        draw.text(
                            (centered_x + shadow_info['offset_x'], y_pos + shadow_info['offset_y']),
                            str(text_value), fill=shadow_info['color'], font=styled_font
                        )
                
                # Render text with center alignment
                # For cursive fonts, no need for italic simulation - they're naturally cursive
                # For non-cursive fonts with italic style, apply simulation
                if font_style in ['italic', 'oblique'] and pos.get('fontFamily', 'Arial') not in ['Dancing Script', 'Great Vibes', 'Pacifico', 'Allura', 'Alex Brush']:
                    for offset in range(3):
                        draw.text((centered_x + offset, y_pos), str(text_value), fill=color, font=styled_font)
                else:
                    draw.text((centered_x, y_pos), str(text_value), fill=color, font=styled_font)

        # Handle custom text separately (not part of doctor info centering)
        # Handle custom text separately (not part of doctor info centering) - FIXED POSITION
        if 'customText' in all_text_data and 'customText' in positions and all_text_data['customText']:
            field_name = 'customText'
            text_value = all_text_data[field_name]
            pos = positions[field_name]
            font_size = int(pos.get('fontSize', 40))
            color = pos.get('color', 'black')
            font_weight = pos.get('fontWeight', 'normal')
            font_family = pos.get('fontFamily', 'Arial')
            font_style = pos.get('fontStyle', 'normal')

            styled_font = get_font(font_family, font_size, font_weight, font_style)

            # Use original fixed position for custom text (no responsive centering)
            x_pos = int(pos['x'])
            y_pos = int(pos['y'])

            text_shadow = pos.get('textShadow', 'none')
            if text_shadow != 'none':
                shadow_info = parse_css_shadow(text_shadow)
                if shadow_info:
                    draw.text(
                        (x_pos + shadow_info['offset_x'], y_pos + shadow_info['offset_y']),
                        str(text_value), fill=shadow_info['color'], font=styled_font
                    )

            if font_style in ['italic', 'oblique'] and font_family not in ['Dancing Script', 'Great Vibes', 'Pacifico', 'Allura', 'Alex Brush']:
                for offset in range(3):
                    draw.text((x_pos + offset, y_pos), str(text_value), fill=color, font=styled_font)
            else:
                draw.text((x_pos, y_pos), str(text_value), fill=color, font=styled_font)
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

        output_dir = os.path.join(settings.MEDIA_ROOT, "temp")

        # Render brands in predefined area with smart layout
        if selected_brand_ids is None:
            selected_brand_ids = content_data.get('selected_brands', [])
        
        print(f"Final selected_brand_ids after processing: {selected_brand_ids}")
        print(f"Template brand_area_settings: {template.brand_area_settings}")
        print(f"Brand area enabled: {template.brand_area_settings.get('enabled', False) if template.brand_area_settings else False}")
        logger.info(f"Template ID: {template.id}, Template name: {template.name}")
        logger.info(f"Brand area settings: {template.brand_area_settings}")
        logger.info(f"Selected brand IDs: {selected_brand_ids}")
        
        print(f"Checking condition: selected_brand_ids={bool(selected_brand_ids)}, has_area_settings={bool(template.brand_area_settings)}, area_enabled={template.brand_area_settings.get('enabled', False) if template.brand_area_settings else False}")

        if selected_brand_ids and template.brand_area_settings and template.brand_area_settings.get('enabled', False):
            print("CONDITION MET - About to render brands")
            print(f"Rendering {len(selected_brand_ids)} brands in defined area")
            brands = Brand.objects.filter(id__in=selected_brand_ids)
            print(f"Found {brands.count()} brands to render")
            
            # ADD DETAILED DEBUG
            for brand in brands:
                print(f"Brand: {brand.name}, Image: {brand.brand_image}")
                if brand.brand_image:
                    print(f"Brand image path: {brand.brand_image.path}")
                    print(f"Path exists: {os.path.exists(brand.brand_image.path)}")
            
            print(f"About to call render_brands_in_area with area: {template.brand_area_settings}")
            
            try:
                # Ensure template_image is in RGBA mode before brand rendering
                if template_image.mode != 'RGBA':
                    template_image = template_image.convert('RGBA')
                    
                render_brands_in_area(template_image, brands, template.brand_area_settings)
                print("Successfully finished calling render_brands_in_area")
            except Exception as e:
                print(f"ERROR in render_brands_in_area: {e}")
                import traceback
                traceback.print_exc()
        else:
            print("CONDITION FAILED - Brand rendering skipped")
            if not selected_brand_ids:
                logger.info("No brands selected")
                print("- No selected_brand_ids")
            elif not template.brand_area_settings:
                logger.info("No brand area settings defined for template")
                print("- No brand_area_settings")
            elif not template.brand_area_settings.get('enabled', False):
                logger.info("Brand area not enabled for template")
                print("- Brand area not enabled")

        # Save the final image AFTER all operations including brand rendering
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"temp_image_{uuid.uuid4().hex}.png")
        
        # Convert to RGB before saving to ensure compatibility
        if template_image.mode == 'RGBA':
            # Create white background and paste RGBA image on it
            rgb_image = Image.new('RGB', template_image.size, (255, 255, 255))
            rgb_image.paste(template_image, mask=template_image.split()[-1])
            rgb_image.save(output_path)
        else:
            template_image.save(output_path)
        
        return output_path
    
    except Exception as e:
        logger.error(f"Image generation error: {e}")
        raise
    finally:
        # Comprehensive cleanup
        if template_image is not None:
            try:
                template_image.close()
                del template_image
            except:
                pass
        if draw is not None:
            try:
                del draw
            except: 
                pass
        # Clean up any brand images
        for brand_img in brand_images:
            try:
                brand_img.close()
                del brand_img
            except:
                pass
        
        # Force garbage collection
        import gc
        gc.collect()

def render_brands_in_area(template_image, brands, area_settings):
    """Render brands using predefined slots with smart centering"""
    print(f"INSIDE render_brands_in_area with {brands.count()} brands")
    print(f"Area settings: {area_settings}")
    
    if not brands or not area_settings.get('enabled'):
        print("Exiting early - no brands or area not enabled")
        return
        
    area_x = area_settings.get('x', 50)
    area_y = area_settings.get('y', 400)
    area_width = area_settings.get('width', 700)
    area_height = area_settings.get('height', 150)
    slots = area_settings.get('slots', [])
    
    if not slots:
        print("No slots defined, exiting")
        return
    
    print(f"Area position: ({area_x}, {area_y})")
    print(f"Area size: {area_width}x{area_height}")
    print(f"Available slots: {len(slots)}")
    
    # Get only the slots we need (based on number of brands)
    brands_list = list(brands)
    needed_slots = slots[:len(brands_list)]
    
    print(f"Using {len(needed_slots)} slots for {len(brands_list)} brands")
    
    # Calculate bounding box of needed slots for centering
    if len(needed_slots) < len(slots):
        min_x = min(slot['x'] for slot in needed_slots)
        max_x = max(slot['x'] + slot['width'] for slot in needed_slots)
        min_y = min(slot['y'] for slot in needed_slots)
        max_y = max(slot['y'] + slot['height'] for slot in needed_slots)
        
        used_width = max_x - min_x
        used_height = max_y - min_y
        
        # Calculate centering offset
        center_offset_x = (area_width - used_width) // 2 - min_x
        center_offset_y = (area_height - used_height) // 2 - min_y
        
        print(f"Centering offset: ({center_offset_x}, {center_offset_y})")
    else:
        # Using all slots, no centering needed
        center_offset_x = 0
        center_offset_y = 0
    
    # Render brands in slots
    for i, (brand, slot) in enumerate(zip(brands_list, needed_slots)):
        print(f"Processing brand {i+1}: {brand.name}")
        
        if brand.brand_image and brand.brand_image.path and os.path.exists(brand.brand_image.path):
            try:
                # Calculate final position with centering offset
                final_x = area_x + slot['x'] + center_offset_x
                final_y = area_y + slot['y'] + center_offset_y
                slot_width = slot['width']
                slot_height = slot['height']
                
                print(f"Slot {i+1} position: ({final_x}, {final_y})")
                print(f"Slot {i+1} size: {slot_width}x{slot_height}")
                
                # Load and resize brand image with memory management
                brand_img = None
                try:
                    if not os.path.exists(brand.brand_image.path):
                        logger.warning(f"Brand image file not found: {brand.brand_image.path}")
                        continue
                        
                    brand_img = Image.open(brand.brand_image.path)

                    # Check image size before processing
                    if brand_img.size[0] > 1000 or brand_img.size[1] > 1000:
                        brand_img.thumbnail((1000, 1000), Image.Resampling.LANCZOS)

                    # Convert to RGB safely
                    if brand_img.mode != 'RGB':
                        try:
                            rgb_img = Image.new('RGB', brand_img.size, (255, 255, 255))
                            rgb_img.paste(brand_img.convert('RGBA'), (0, 0))
                            brand_img.close()
                            brand_img = rgb_img
                        except Exception as e:
                            logger.warning(f"Image conversion failed for {brand.name}: {e}")
                            brand_img = brand_img.convert('RGB')
                    
                    # Resize brand image
                    brand_img = brand_img.resize((slot_width, slot_height), Image.Resampling.LANCZOS)
                    
                    # Paste brand image
                    if template_image.mode != 'RGBA':
                        template_image = template_image.convert('RGBA')
                    
                    template_image.paste(brand_img, (final_x, final_y))
                    
                except (IOError, OSError) as e:
                    logger.warning(f"Failed to process brand image {brand.id}: {e}")
                    continue
                finally:
                    if brand_img is not None:
                        try:
                            brand_img.close()
                        except:
                            pass
                
                logger.info(f"Rendered brand {brand.name} in slot {i+1} at ({final_x}, {final_y})")
                print(f"Successfully pasted brand {brand.name} at ({final_x}, {final_y})")
                
            except Exception as e:
                print(f"Failed to render brand {brand.name}: {e}")
                logger.error(f"Failed to render brand {brand.name}: {e}")

@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def generate_custom_video_task(self, doctor_id, template_id, output_path, *args):
    """Generate video in background - placeholder for video functionality"""
    logger.info(f"Starting video generation for doctor {doctor_id}")
    
    try:
        return {"status": "success", "message": "Video generated"}
        
    except Exception as e:
        logger.error(f"Video generation failed: {e}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=60, exc=e)
        raise