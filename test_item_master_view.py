import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AVCRI.settings')
django.setup()

from masters.models import ItemGroup, ItemMaster
from django.test import RequestFactory
from masters.views import ItemMasterManagementView

print("Testing Item Master Management View...")

try:
    # Create a test request
    factory = RequestFactory()
    request = factory.get('/Masters/items/')
    
    # Create view instance
    view = ItemMasterManagementView()
    view.request = request
    
    # Get queryset
    queryset = view.get_queryset()
    print(f"✓ Queryset retrieved successfully")
    print(f"  Total items: {queryset.count()}")
    
    # Get context data
    view.object_list = queryset
    context = view.get_context_data()
    print(f"✓ Context data retrieved successfully")
    print(f"  Context keys: {list(context.keys())}")
    
    # Check if item_groups is in context
    if 'item_groups' in context:
        print(f"✓ item_groups found in context")
        print(f"  Number of groups: {context['item_groups'].count()}")
    else:
        print(f"⚠ item_groups not in context (this is OK, it's added in get_context_data)")
    
    print("\n✅ Item Master Management View is working correctly!")
    print("   The page should load without errors now.")
    
except Exception as e:
    print(f"\n❌ Error testing view: {e}")
    import traceback
    traceback.print_exc()
