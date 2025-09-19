from django.db import models
from django.utils import timezone
import os

class Designation(models.Model):
    login_code = models.CharField(max_length=100, unique=True, db_index=True)
    rbm_region = models.CharField(max_length=100, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['login_code', 'rbm_region']),
            models.Index(fields=['rbm_region']),
        ]

    def __str__(self):
        return f"{self.login_code} -> {self.rbm_region}"


class Employee(models.Model):
    USER_TYPE_CHOICES = [
        ('Employee', 'Employee'),
        ('Admin', 'Admin'),
        ('SuperAdmin', 'SuperAdmin'),
    ]

    employee_id = models.CharField(max_length=100, unique=True, db_index=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, null=True, blank=True)
    email = models.EmailField(unique=True, null=True, blank=True)
    phone = models.CharField(max_length=15, null=True, blank=True)
    department = models.CharField(max_length=100, null=True, blank=True)
    date_joined = models.DateField(auto_now_add=True)
    user_type = models.CharField(max_length=20, choices=USER_TYPE_CHOICES, default='Employee')
    status = models.BooleanField(default=True)
    login_date = models.DateTimeField(default=timezone.now)
    
    # NEW FIELDS FOR DESIGNATION SYSTEM
    designation = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    rbm_region = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    
    # Keep old rbm field for backward compatibility
    rbm = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='team_members'
    )
    city = models.CharField(max_length=30,blank=True, null=True)
    has_logged_in = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"



class EmployeeLoginHistory(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='login_history')

    # Snapshot fields (renamed to avoid conflict)
    employee_identifier = models.CharField(max_length=100,null=True, blank=True)  # Was employee_id
    name = models.CharField(max_length=200,null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    phone = models.CharField(max_length=15, null=True, blank=True)
    department = models.CharField(max_length=100, null=True, blank=True)
    user_type = models.CharField(max_length=20,null=True, blank=True)
    login_time = models.DateTimeField(default=timezone.now,null=True, blank=True)

    def __str__(self):
        return f"{self.name} logged in at {self.login_time}"


class DoctorVideo(models.Model):
    name = models.CharField(max_length=285, db_index=True)
    designation = models.CharField(max_length=255)
    clinic = models.CharField(max_length=255)
    city = models.CharField(max_length=100, db_index=True)
    state = models.CharField(max_length=100, null=True, blank=True)
    image = models.ImageField(upload_to='doctor_images/')
    specialization = models.CharField(max_length=255, db_index=True)
    specialization_key = models.CharField(max_length=255, null=True, blank=True)
    mobile_number = models.CharField(max_length=15, db_index=True)
    whatsapp_number = models.CharField(max_length=15)
    description = models.TextField()
    output_video = models.FileField(upload_to='output/', null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    employee = models.ForeignKey(Employee,  on_delete=models.CASCADE, related_name='doctors_video',null=True, blank=True)

    def __str__(self):
        return self.name

    class Meta:
        unique_together = [['employee', 'mobile_number']]
        indexes = [
            models.Index(fields=['employee', 'created_at']),
            models.Index(fields=['mobile_number', 'name']),
            models.Index(fields=['specialization', 'city']),
            models.Index(fields=['created_at', 'employee']),  # For pagination
            models.Index(fields=['name', 'specialization']),  # For search
        ]


class VideoTemplates(models.Model):

    name = models.CharField(max_length=100,null=True, blank=True)
    template_video = models.FileField(upload_to='video-template/')
    created_by = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='created_templates',
        null=True,
        blank=True
    )
    is_public = models.BooleanField(default=True)
    base_x_axis = models.CharField(max_length=100,null=True, blank=True)
    base_y_axis = models.CharField(max_length=100,null=True, blank=True)
    overlay_x = models.CharField(max_length=100,null=True, blank=True)
    overlay_y = models.CharField(max_length=100,null=True, blank=True)
    time_duration = models.CharField(max_length=100,null=True, blank=True)
    line_spacing = models.CharField(max_length=100,null=True, blank=True)
    resolution = models.CharField(max_length=100,null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.BooleanField(default=True)


    #! Added By Prathamesh-

    template_type = models.CharField(
        max_length=20,
        choices=[('video', 'Video Template'), ('image', 'Image Template')],
        default='video'
    )
    template_image = models.ImageField(upload_to='image-templates/', null=True, blank=True)
    text_positions = models.JSONField(null=True, blank=True, help_text="JSON format: {'field_name': {'x': 100, 'y': 50}}")
    custom_text = models.TextField(null=True, blank=True, help_text="Template's default text like 'Good Morning'")  # ADD THIS


    brand_area_settings = models.JSONField(
        null=True, blank=True,
        help_text="Brand placement area: {'enabled': True, 'x': 50, 'y': 400, 'width': 700, 'height': 150, 'brandWidth': 100, 'brandHeight': 60}"
    )
    def __str__(self):
        return f"Video for {self.template_video} and {self.template_image}"



#! Added By Prathamesh-

class ImageContent(models.Model):
    template = models.ForeignKey(
        VideoTemplates,
        on_delete=models.CASCADE,
        limit_choices_to={'template_type': 'image'},
        related_name='image_contents'
    )
    # CHANGE: Link to DoctorVideo instead of Employee
    doctor = models.ForeignKey(
        DoctorVideo,
        on_delete=models.CASCADE,
        related_name='image_contents'
    )

    # Store dynamic content as JSON
    content_data = models.JSONField(
        help_text="Store form data like: {'name': 'John', 'message': 'Good Morning'}"
    )

    # Generated output image
    output_image = models.ImageField(upload_to='generated-images/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Image Content for Dr. {self.doctor.name} - {self.template.name}"

    class Meta:
        ordering = ['-created_at']


# def doctor_video_upload_path(instance, filename):
#     employee_id = instance.doctor.employee.id if instance.doctor and instance.doctor.employee else 'unknown_employee'
#     doctor_id = instance.doctor.id if instance.doctor else 'unknown_doctor'
#     # template_id = instance.template.id if instance.template else 'unknown_template'

#     return os.path.join('output', str(employee_id), str(doctor_id),filename)

def doctor_video_upload_path(instance, filename):
    employee_id = (
        instance.doctor.employee.id
        if instance.doctor and hasattr(instance.doctor, 'employee') and instance.doctor.employee
        else 'unknown_employee'
    )
    doctor_id = instance.doctor.id if instance.doctor else 'unknown_doctor'
    return os.path.join('output', str(employee_id), str(doctor_id), filename)



class Brand(models.Model):
    CATEGORY_CHOICES = [
        ('PAIN', 'Pain'),
        ('STROKE_PREVENTION', 'In Prevention of Stroke'),
        ('NEURO_PROTECTORS', 'Neuro-Protectors'),
        ('MIGRAINE_VERTIGO', 'Migraine & Vertigo'),
        ('ANTI_PSYCHOTICS', 'Anti-Psychotics'),
        ('ANTI_DEPRESSANT', 'Anti-Depressant'),
        ('ANTI_EPILEPTIC', 'Anti-Epileptic'),
        ('SEDATIVES', 'Sedatives / Anti Anxiolytics'),
    ]

    name = models.CharField(max_length=100)
    brand_image = models.ImageField(upload_to='brand-images/')
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default='PAIN')
    uploaded_by = models.ForeignKey(
    'Employee',
    on_delete=models.CASCADE,
    related_name='uploaded_brands',
    limit_choices_to={'user_type__in': ['Admin', 'SuperAdmin']}
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.get_category_display()})"


class DoctorUsageHistory(models.Model):
    doctor = models.ForeignKey(DoctorVideo, on_delete=models.CASCADE, related_name='usage_history')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    template = models.ForeignKey(VideoTemplates, on_delete=models.CASCADE)
    generated_at = models.DateTimeField(auto_now_add=True)
    content_type = models.CharField(max_length=20, default='image')  # image/video
    image_content = models.ForeignKey(ImageContent, on_delete=models.CASCADE, null=True, blank=True)

    class Meta:
        ordering = ['-generated_at']