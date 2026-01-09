import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AVCRI.settings')
django.setup()

from masters.models import ItemGroup

print("Testing ItemGroup model access...")

try:
    # Try to query ItemGroup
    count = ItemGroup.objects.count()
    print(f"✓ ItemGroup.objects.count() = {count}")
    
    # Try to get all items
    items = ItemGroup.objects.all()[:5]
    print(f"✓ ItemGroup.objects.all() works")
    
    for item in items:
        print(f"  - {item.name} (active: {item.is_active})")
    
    if count == 0:
        print("\n⚠ No ItemGroup records found. Creating a test record...")
        test_group = ItemGroup.objects.create(name="Test Group", is_active=True)
        print(f"✓ Created test ItemGroup: {test_group.name}")
    
    print("\n✅ ItemGroup model is working correctly!")
    
except Exception as e:
    print(f"\n❌ Error accessing ItemGroup: {e}")
    import traceback
    traceback.print_exc()
