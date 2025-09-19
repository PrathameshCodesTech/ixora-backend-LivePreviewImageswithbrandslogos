# from django.contrib import admin
# from .models import Employee
# from .models import Doctor

# @admin.register(Employee)
# class EmployeeAdmin(admin.ModelAdmin):
#     list_display = ('first_name', 'last_name', 'email', 'department', 'date_joined')



# admin.site.register(Doctor)


#! Prathamesh
from django.contrib import admin
from .models import Employee, EmployeeLoginHistory, DoctorVideo, VideoTemplates, ImageContent, Brand,Designation

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
            'fields': ('department', 'city', 'user_type', 'designation', 'rbm_region', 'rbm')
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





# DoctorVideo Admin
# DoctorVideo Admin
@admin.register(DoctorVideo)
class DoctorVideoAdmin(admin.ModelAdmin):
    list_display = ['name', 'clinic', 'city', 'state', 'specialization', 'mobile_number', 'employee_designation', 'employee_rbm', 'created_at', 'has_output_video', 'has_image_contents', 'duplicate_count', 'total_usage_count']
    list_filter = ['city', 'state', 'specialization', 'employee', 'created_at', 'employee__designation', 'employee__rbm_region']
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
    
    def duplicate_count(self, obj):
        """Count how many other employees have this same doctor (by mobile number)"""
        count = DoctorVideo.objects.filter(mobile_number=obj.mobile_number).exclude(id=obj.id).count()
        return count
    duplicate_count.short_description = 'Duplicate Doctors'
    duplicate_count.admin_order_field = 'mobile_number'

    def total_usage_count(self, obj):
        """Count total image generations for this doctor"""
        return obj.image_contents.count()
    total_usage_count.short_description = 'Images Generated'
    total_usage_count.admin_order_field = 'image_contents'
    
    def get_queryset(self, request):
        """Optimize queryset with prefetch for better performance"""
        return super().get_queryset(request).select_related('employee').prefetch_related('image_contents')

    def changelist_view(self, request, extra_context=None):
        """Add duplicate statistics to the changelist view"""
        from django.db.models import Count
        
        # Get duplicate statistics
        duplicate_stats = DoctorVideo.objects.values('mobile_number').annotate(
            duplicate_count=Count('id')
        ).filter(duplicate_count__gt=1).order_by('-duplicate_count')
        
        # Get most active doctors by image generation
        active_doctors = DoctorVideo.objects.annotate(
            image_count=Count('image_contents')
        ).filter(image_count__gt=0).order_by('-image_count')[:10]
        
        extra_context = extra_context or {}
        extra_context['duplicate_stats'] = duplicate_stats[:10]  # Top 10 duplicates
        extra_context['active_doctors'] = active_doctors
        extra_context['total_duplicates'] = sum(stat['duplicate_count'] - 1 for stat in duplicate_stats)
        
        return super().changelist_view(request, extra_context=extra_context)
    
    def employee_designation(self, obj):
        """Show employee's designation (login ID)"""
        if obj.employee:
            return obj.employee.designation or obj.employee.employee_id
        return "No Employee"
    employee_designation.short_description = 'Created By'
    employee_designation.admin_order_field = 'employee__designation'

    def employee_rbm(self, obj):
        """Show employee's RBM region"""
        if obj.employee:
            return obj.employee.rbm_region or "No RBM"
        return "No Employee"
    employee_rbm.short_description = 'RBM Region'
    employee_rbm.admin_order_field = 'employee__rbm_region'


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



@admin.register(Designation)
class DesignationAdmin(admin.ModelAdmin):
    list_display = ['login_code', 'rbm_region', 'employee_count', 'created_at']
    list_filter = ['rbm_region', 'created_at']
    search_fields = ['login_code', 'rbm_region']
    ordering = ['rbm_region', 'login_code']
    
    def employee_count(self, obj):
        """Count employees using this designation"""
        return Employee.objects.filter(designation=obj.login_code).count()
    employee_count.short_description = 'Employees Using'



# Additional Admin Customizations
admin.site.site_header = "Employee Management System"
admin.site.site_title = "Employee Admin"
admin.site.index_title = "Welcome to Employee Management System"