"""
Test Instagram URL importer with real URLs
"""

import asyncio
from viraltracker.core.database import get_supabase_client
from viraltracker.importers import InstagramURLImporter


async def test_import():
    # Get platform ID
    supabase = get_supabase_client()
    platform = supabase.table('platforms').select('id').eq('slug', 'instagram').single().execute()
    platform_id = platform.data['id']

    # Get project ID
    project = supabase.table('projects').select('id').eq('slug', 'yakety-pack-instagram').single().execute()
    project_id = project.data['id']

    # Initialize importer
    importer = InstagramURLImporter(platform_id)

    # Test URLs - popular Instagram Reels
    test_urls = [
        'https://www.instagram.com/reel/C_YqVuEP2Ty/',  # Example reel
        'https://www.instagram.com/p/C_Xt5wIPqRz/',    # Example post
    ]

    print(f"Testing Instagram URL Importer")
    print(f"Platform ID: {platform_id}")
    print(f"Project ID: {project_id}")
    print(f"=" * 60)

    for url in test_urls:
        print(f"\n🔍 Testing: {url}")
        try:
            result = await importer.import_url(
                url=url,
                project_id=project_id,
                is_own_content=False,
                notes='Test import from Phase 2'
            )
            print(f"✅ Success!")
            print(f"   Post ID: {result.get('id')}")
            print(f"   Post URL: {result.get('post_url')}")
            print(f"   Caption: {result.get('caption', '')[:100]}...")
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()


if __name__ == '__main__':
    asyncio.run(test_import())
