# from django.contrib import admin
# from .models import Employee
# from .models import Doctor

# @admin.register(Employee)
# class EmployeeAdmin(admin.ModelAdmin):
#     list_display = ('first_name', 'last_name', 'email', 'department', 'date_joined')



# admin.site.register(Doctor)


#! Prathamesh
from django.contrib import admin
from .models import Employee, EmployeeLoginHistory, DoctorVideo, Doctor, VideoTemplates, DoctorOutputVideo, ImageContent, Brand

# Employee Admin
@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ['employee_id', 'first_name', 'last_name', 'email', 'department', 'user_type', 'status', 'city', 'has_logged_in', 'date_joined']
    list_filter = ['user_type', 'status', 'department', 'city', 'has_logged_in', 'date_joined']
    search_fields = ['employee_id', 'first_name', 'last_name', 'email', 'department']
    ordering = ['-date_joined']
    readonly_fields = ['date_joined', 'login_date']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('employee_id', 'first_name', 'last_name', 'email', 'phone')
        }),
        ('Work Details', {
            'fields': ('department', 'city', 'user_type', 'rbm')
        }),
        ('Status & Dates', {
            'fields': ('status', 'has_logged_in', 'date_joined', 'login_date')
        }),
    )


# Employee Login History Admin
@admin.register(EmployeeLoginHistory)
class EmployeeLoginHistoryAdmin(admin.ModelAdmin):
    list_display = ['employee', 'name', 'department', 'user_type', 'login_time']
    list_filter = ['user_type', 'department', 'login_time']
    search_fields = ['employee__employee_id', 'name', 'email', 'department']
    ordering = ['-login_time']
    readonly_fields = ['login_time']
    
    fieldsets = (
        ('Employee Reference', {
            'fields': ('employee', 'employee_identifier')
        }),
        ('Snapshot Data', {
            'fields': ('name', 'email', 'phone', 'department', 'user_type')
        }),
        ('Login Info', {
            'fields': ('login_time',)
        }),
    )


# Doctor Admin
@admin.register(Doctor)
class DoctorAdmin(admin.ModelAdmin):
    list_display = ['name', 'specialization', 'clinic', 'city', 'state', 'employee', 'has_output_video']
    list_filter = ['specialization', 'city', 'state', 'employee']
    search_fields = ['name', 'clinic', 'city', 'specialization', 'mobile_number']
    ordering = ['name']
    
    fieldsets = (
        ('Doctor Information', {
            'fields': ('name', 'designation', 'specialization', 'image')
        }),
        ('Practice Details', {
            'fields': ('clinic', 'city', 'state', 'description')
        }),
        ('Contact Information', {
            'fields': ('mobile_number', 'whatsapp_number')
        }),
        ('System Data', {
            'fields': ('employee', 'output_video')
        }),
    )
    
    def has_output_video(self, obj):
        return bool(obj.output_video)
    has_output_video.boolean = True
    has_output_video.short_description = 'Has Video'


# DoctorVideo Admin
@admin.register(DoctorVideo)
class DoctorVideoAdmin(admin.ModelAdmin):
    list_display = ['name', 'clinic', 'city', 'state', 'specialization', 'employee', 'created_at', 'has_output_video', 'has_image_contents']
    list_filter = ['city', 'state', 'specialization', 'employee', 'created_at']
    search_fields = ['name', 'clinic', 'city', 'specialization', 'mobile_number']
    ordering = ['-created_at']
    readonly_fields = ['created_at']
    
    fieldsets = (
        ('Doctor Information', {
            'fields': ('name', 'designation', 'specialization', 'specialization_key', 'image')
        }),
        ('Practice Details', {
            'fields': ('clinic', 'city', 'state', 'description')
        }),
        ('Contact Information', {
            'fields': ('mobile_number', 'whatsapp_number')
        }),
        ('System Data', {
            'fields': ('employee', 'output_video', 'created_at')
        }),
    )
    
    def has_output_video(self, obj):
        return bool(obj.output_video)
    has_output_video.boolean = True
    has_output_video.short_description = 'Has Video'
    
    def has_image_contents(self, obj):
        return obj.image_contents.count() > 0
    has_image_contents.boolean = True
    has_image_contents.short_description = 'Has Generated Images'



# VideoTemplates Admin
@admin.register(VideoTemplates)
class VideoTemplatesAdmin(admin.ModelAdmin):
    list_display = ['name', 'template_type', 'status', 'created_at', 'has_video', 'has_image', 'has_brand_area']
    list_filter = ['template_type', 'status', 'created_at']
    search_fields = ['name']
    ordering = ['-created_at']
    readonly_fields = ['created_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'template_type', 'status', 'created_at')
        }),
        ('Video Template Settings', {
            'fields': ('template_video', 'base_x_axis', 'base_y_axis', 'overlay_x', 'overlay_y', 'time_duration', 'line_spacing', 'resolution'),
            'classes': ('collapse',),
            'description': 'Settings specific to video templates'
        }),
        ('Image Template Settings', {
            'fields': ('template_image', 'text_positions', 'custom_text', 'brand_area_settings'),
            'classes': ('collapse',),
            'description': 'Settings specific to image templates. Text positions should be JSON format: {"field_name": {"x": 100, "y": 50}}'
        }),
    )
    
    def has_video(self, obj):
        return bool(obj.template_video)
    has_video.boolean = True
    has_video.short_description = 'Has Video File'
    
    def has_image(self, obj):
        return bool(obj.template_image)
    has_image.boolean = True
    has_image.short_description = 'Has Image File'

    def has_brand_area(self, obj):
        return bool(obj.brand_area_settings and obj.brand_area_settings.get('enabled', False))
    has_brand_area.boolean = True
    has_brand_area.short_description = 'Has Brand Area'

# DoctorOutputVideo Admin
@admin.register(DoctorOutputVideo)
class DoctorOutputVideoAdmin(admin.ModelAdmin):
    list_display = ['id', 'doctor_name', 'template_name', 'created_at', 'has_video_file']
    list_filter = ['template__name', 'created_at', 'doctor__employee']
    search_fields = ['doctor__name', 'template__name', 'doctor__clinic']
    ordering = ['-created_at']
    readonly_fields = ['created_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('doctor', 'template', 'created_at')
        }),
        ('Generated Output', {
            'fields': ('video_file',)
        }),
    )
    
    def doctor_name(self, obj):
        return obj.doctor.name if obj.doctor else 'N/A'
    doctor_name.short_description = 'Doctor'
    
    def template_name(self, obj):
        return obj.template.name if obj.template else 'N/A'
    template_name.short_description = 'Template'
    
    def has_video_file(self, obj):
        return bool(obj.video_file)
    has_video_file.boolean = True
    has_video_file.short_description = 'Has Video'


# ImageContent Admin (New)
@admin.register(ImageContent)
class ImageContentAdmin(admin.ModelAdmin):
    list_display = ['id', 'doctor_name', 'doctor_clinic', 'template_name', 'created_at', 'has_output_image', 'content_preview']
    list_filter = ['template__name', 'created_at', 'doctor__employee', 'doctor__city']
    search_fields = ['doctor__name', 'template__name', 'doctor__clinic', 'doctor__city']
    ordering = ['-created_at']
    readonly_fields = ['created_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('template', 'doctor', 'created_at')
        }),
        ('Content Data', {
            'fields': ('content_data',),
            'description': 'JSON data containing the form inputs used to generate the image'
        }),
        ('Generated Output', {
            'fields': ('output_image',),
            'description': 'The generated image with text overlay'
        }),
    )
    
    def doctor_name(self, obj):
        return obj.doctor.name
    doctor_name.short_description = 'Doctor'
    
    def doctor_clinic(self, obj):
        return obj.doctor.clinic
    doctor_clinic.short_description = 'Clinic'
    
    def template_name(self, obj):
        return obj.template.name
    template_name.short_description = 'Template'
    
    def has_output_image(self, obj):
        return bool(obj.output_image)
    has_output_image.boolean = True
    has_output_image.short_description = 'Image Generated'
    
    def content_preview(self, obj):
        if obj.content_data:
            # Show first few fields from content_data
            preview_items = []
            for key, value in list(obj.content_data.items())[:3]:
                preview_items.append(f"{key}: {str(value)[:20]}...")
            return " | ".join(preview_items)
        return "No content"
    content_preview.short_description = 'Content Preview'

@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'uploaded_by', 'uploaded_at')
    list_filter = ('category', 'uploaded_by', 'uploaded_at')
    search_fields = ('name', 'uploaded_by__first_name', 'uploaded_by__last_name')
    ordering = ('category', 'name')



# Additional Admin Customizations
admin.site.site_header = "Employee Management System"
admin.site.site_title = "Employee Admin"
admin.site.index_title = "Welcome to Employee Management System"