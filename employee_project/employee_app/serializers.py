from rest_framework import serializers
from .models import Employee,DoctorVideo,VideoTemplates,ImageContent,Brand



class EmployeeLoginSerializer(serializers.Serializer):
    employee_id = serializers.CharField()
    

class EmployeeSerializer(serializers.ModelSerializer):
    rbm_name = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = '__all__'
        read_only_fields = ['rbm_name']

    def get_rbm_name(self, obj):
        if obj.rbm:
            return f"{obj.rbm.first_name} {obj.rbm.last_name or ''}".strip()
        return None
    

class DoctorSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(required=False, allow_null=True)  # Handle image field if null
   
    class Meta:
        model = DoctorVideo
        fields = ['id', 'name', 'designation', 'clinic', 'city', 'state', 'image', 'specialization', 'mobile_number', 'whatsapp_number', 'description', 'output_video', 'employee']




class DoctorVideoSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(required=False, allow_null=True)
    # latest_output_video = serializers.SerializerMethodField()
    latest_output_image = serializers.SerializerMethodField()  # ADD THIS
    employee_name = serializers.SerializerMethodField()
    rbm_name = serializers.SerializerMethodField()

    class Meta:
        model = DoctorVideo
        fields = [
            'id', 'name', 'designation', 'clinic', 'city', 'state',
            'image', 'specialization', 'specialization_key',
            'mobile_number', 'whatsapp_number', 'description',
            'output_video', 'created_at', 'employee',
            'latest_output_image',  # ADD latest_output_image HERE
            'employee_name', 'rbm_name',
        ]

    def get_latest_output_video(self, obj):
        []

    def get_latest_output_image(self, obj):  # ADD THIS METHOD
        images = ImageContent.objects.filter(doctor=obj).order_by('-id')
        return ImageContentSerializer(images, many=True).data

    def get_employee_name(self, obj):
        if obj.employee:
            # Show designation (login ID) instead of full name
            return obj.employee.designation or obj.employee.employee_id or f"{obj.employee.first_name} {obj.employee.last_name}".strip()
        return None

    def get_rbm_name(self, obj):
        if obj.employee and obj.employee.rbm_region:
            return obj.employee.rbm_region
        elif obj.employee and obj.employee.rbm:
            return f"{obj.employee.rbm.first_name} {obj.employee.rbm.last_name}".strip()
        return None

    def validate(self, data):
        print(f"🔍 SERIALIZER VALIDATION DATA: {data}")
        
        # Check required fields
        required_fields = ['name', 'clinic', 'city', 'mobile_number', 'whatsapp_number']
        for field in required_fields:
            if not data.get(field):
                print(f"🔍 MISSING FIELD: {field}")
                raise serializers.ValidationError(f"{field} is required")
        
        return data
    
class VideoTemplatesSerializer(serializers.ModelSerializer):

    class Meta:
        model = VideoTemplates
        fields = '__all__'
        
    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Ensure template_type is always included
        if not data.get('template_type'):
            data['template_type'] = 'video'  # Default fallback
        
        # Ensure custom_text is included for image templates
        if instance.template_type == 'image' and not data.get('custom_text'):
            data['custom_text'] = instance.custom_text or ''
            
        return data
   


#! Added by Prathamesh-

class ImageContentSerializer(serializers.ModelSerializer):
    doctor_name = serializers.SerializerMethodField()
    doctor_clinic = serializers.SerializerMethodField()
    template_name = serializers.SerializerMethodField()
    output_image_url = serializers.SerializerMethodField()
    
    class Meta:
        model = ImageContent
        fields = [
            'id', 'template', 'doctor', 'content_data', 
            'output_image', 'created_at', 'doctor_name', 
            'doctor_clinic', 'template_name', 'output_image_url'
        ]
        read_only_fields = ['id', 'created_at', 'output_image']
    
    def get_doctor_name(self, obj):
        return obj.doctor.name
    
    def get_doctor_clinic(self, obj):
        return obj.doctor.clinic
    
    def get_template_name(self, obj):
        return obj.template.name
    
    def get_output_image_url(self, obj):
        if obj.output_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.output_image.url)
            return obj.output_image.url
        return None


class ImageTemplateSerializer(serializers.ModelSerializer):
    template_image_url = serializers.SerializerMethodField()
    
    class Meta:
        model = VideoTemplates
        fields = [
            'id', 'name', 'template_image', 'text_positions', 
            'custom_text', 'brand_area_settings', 'status', 'created_at', 'template_image_url'
        ]
        extra_kwargs = {
            'template_type': {'default': 'image'}
        }
    
    def get_template_image_url(self, obj):
        if obj.template_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.template_image.url)
            return obj.template_image.url
        return None
    
    def validate(self, data):
        # Ensure this is an image template
        data['template_type'] = 'image'
        return data

class BrandSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    uploaded_by = serializers.StringRelatedField()

    class Meta:
        model = Brand
        fields = ['id', 'name', 'brand_image', 'category', 'category_display', 'uploaded_by', 'uploaded_at']

