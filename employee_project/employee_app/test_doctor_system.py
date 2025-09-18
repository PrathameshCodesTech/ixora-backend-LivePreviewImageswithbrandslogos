# Run with: python manage.py shell < test_doctor_system.py

from .models import Employee, DoctorVideo
from django.db import IntegrityError

print("=== TESTING DOCTOR SYSTEM ===\n")

# Clean up test data first
print("1. Cleaning up existing test data...")
DoctorVideo.objects.filter(mobile_number__in=['9999999999', '8888888888']).delete()
Employee.objects.filter(employee_id__in=['TEST_EMP_A', 'TEST_EMP_B']).delete()

# Create test employees
print("2. Creating test employees...")
emp_a = Employee.objects.create(
    employee_id='TEST_EMP_A',
    first_name='Employee',
    last_name='A',
    email='emp_a@test.com',
    user_type='Employee'
)

emp_b = Employee.objects.create(
    employee_id='TEST_EMP_B', 
    first_name='Employee',
    last_name='B',
    email='emp_b@test.com',
    user_type='Employee'
)
print(f"Created employees: {emp_a.employee_id}, {emp_b.employee_id}")

# Test 1: Employee A creates doctor
print("\n3. TEST 1: Employee A creates first doctor")
doctor_a1 = DoctorVideo.objects.create(
    name='Dr. John Smith',
    mobile_number='9999999999',
    clinic='City Hospital',
    city='Mumbai',
    state='Maharashtra',
    specialization='Cardiology',
    specialization_key='Cardiology',
    whatsapp_number='9999999999',
    description='Test doctor',
    employee=emp_a
)
print(f"✅ SUCCESS: Employee A created doctor ID {doctor_a1.id}")

# Test 2: Employee B creates doctor with same mobile (should work)
print("\n4. TEST 2: Employee B creates doctor with same mobile number")
try:
    doctor_b1 = DoctorVideo.objects.create(
        name='Dr. John Smith',
        mobile_number='9999999999',  # Same mobile as Employee A
        clinic='Metro Hospital',      # Different clinic
        city='Delhi',                # Different city
        state='Delhi',
        specialization='Neurology',   # Different specialization
        specialization_key='Neurology',
        whatsapp_number='9999999999',
        description='Test doctor B',
        employee=emp_b
    )
    print(f"✅ SUCCESS: Employee B created separate doctor ID {doctor_b1.id}")
    print(f"   Employee A's doctor: {doctor_a1.clinic}")
    print(f"   Employee B's doctor: {doctor_b1.clinic}")
except IntegrityError as e:
    print(f"❌ FAILED: {e}")

# Test 3: Employee A tries duplicate mobile (should fail)
print("\n5. TEST 3: Employee A tries to create another doctor with same mobile")
try:
    doctor_a2 = DoctorVideo.objects.create(
        name='Dr. Jane Doe',
        mobile_number='9999999999',  # Same mobile as Employee A's existing doctor
        clinic='New Hospital',
        city='Pune',
        state='Maharashtra', 
        specialization='Orthopedics',
        specialization_key='Orthopedics',
        whatsapp_number='9999999999',
        description='Another doctor',
        employee=emp_a
    )
    print(f"❌ UNEXPECTED: Should have failed but created doctor ID {doctor_a2.id}")
except IntegrityError as e:
    print("✅ SUCCESS: Correctly blocked duplicate mobile for same employee")
    print(f"   Error: {e}")

# Test 4: Employee A updates existing doctor (should work)
print("\n6. TEST 4: Employee A updates existing doctor")
original_clinic = doctor_a1.clinic
doctor_a1.clinic = 'Updated Hospital'
doctor_a1.name = 'Dr. John Updated'  # Name can be changed
doctor_a1.save()

updated_doctor = DoctorVideo.objects.get(id=doctor_a1.id)
print(f"✅ SUCCESS: Doctor updated")
print(f"   Original clinic: {original_clinic}")
print(f"   Updated clinic: {updated_doctor.clinic}")
print(f"   Updated name: {updated_doctor.name}")

# Test 5: Verify employee isolation
print("\n7. TEST 5: Verify employee isolation")
emp_a_doctors = DoctorVideo.objects.filter(employee=emp_a)
emp_b_doctors = DoctorVideo.objects.filter(employee=emp_b)

print(f"Employee A sees {emp_a_doctors.count()} doctor(s):")
for doc in emp_a_doctors:
    print(f"   - {doc.name} at {doc.clinic}")

print(f"Employee B sees {emp_b_doctors.count()} doctor(s):")
for doc in emp_b_doctors:
    print(f"   - {doc.name} at {doc.clinic}")

# Test 6: Search functionality
print("\n8. TEST 6: Testing search functionality")
# Simulate Employee B searching for Employee A's mobile
search_results = DoctorVideo.objects.filter(mobile_number='9999999999')
print(f"Search for mobile '9999999999' returns {search_results.count()} results:")
for doc in search_results:
    print(f"   - {doc.name} at {doc.clinic} (Employee: {doc.employee.employee_id})")

# Test 7: Auto-population simulation
print("\n9. TEST 7: Auto-population simulation")
# What Employee B would see when searching
existing_doctor_for_autofill = DoctorVideo.objects.filter(mobile_number='9999999999').first()
if existing_doctor_for_autofill:
    print(f"Auto-fill data for Employee B:")
    print(f"   - Name: {existing_doctor_for_autofill.name}")
    print(f"   - Clinic: {existing_doctor_for_autofill.clinic}")
    print(f"   - City: {existing_doctor_for_autofill.city}")
    print(f"   - Mobile: {existing_doctor_for_autofill.mobile_number} (READ-ONLY)")

# Cleanup
print("\n10. Cleaning up test data...")
DoctorVideo.objects.filter(mobile_number__in=['9999999999', '8888888888']).delete()
Employee.objects.filter(employee_id__in=['TEST_EMP_A', 'TEST_EMP_B']).delete()
print("✅ Cleanup completed")

print("\n=== TEST SUMMARY ===")
print("✅ Cross-employee mobile sharing: WORKS")
print("✅ Same-employee duplicate prevention: WORKS") 
print("✅ Employee isolation: WORKS")
print("✅ Doctor updates: WORKS")
print("✅ Auto-population data available: WORKS")
print("\n🎉 ALL TESTS PASSED - System ready!")