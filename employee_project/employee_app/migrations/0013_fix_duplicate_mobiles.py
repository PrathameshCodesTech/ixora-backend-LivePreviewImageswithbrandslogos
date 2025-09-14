from django.db import migrations
from django.db.models import Count

def fix_duplicate_mobiles(apps, schema_editor):
    DoctorVideo = apps.get_model('employee_app', 'DoctorVideo')
    
    # Find duplicates
    duplicates = DoctorVideo.objects.values('mobile_number').annotate(
        count=Count('mobile_number')
    ).filter(count__gt=1)
    
    for dup in duplicates:
        mobile = dup['mobile_number']
        records = DoctorVideo.objects.filter(mobile_number=mobile).order_by('created_at')
        
        # Keep the first record, modify others
        for i, record in enumerate(records[1:], 1):
            record.mobile_number = f"{mobile}_dup_{i}"
            record.save()

def reverse_fix_duplicate_mobiles(apps, schema_editor):
    # This is irreversible, so we'll just pass
    pass

class Migration(migrations.Migration):
    dependencies = [
        ('employee_app', '0012_alter_doctorvideo_city_and_more'),
    ]

    operations = [
        migrations.RunPython(fix_duplicate_mobiles, reverse_fix_duplicate_mobiles),
    ]