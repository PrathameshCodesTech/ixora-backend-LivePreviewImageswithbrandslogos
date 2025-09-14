from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [
        ('employee_app', '0001_initial'),  # Replace with your latest migration number
    ]

    operations = [
        # Tell Django these fields already exist in the database
        migrations.RunSQL(
            "SELECT 1;",  # No-op SQL
            reverse_sql="SELECT 1;"
        ),
    ]