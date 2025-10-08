from viraltracker.core.database import get_supabase_client

supabase = get_supabase_client()

# Get Wonder Paws product
product = supabase.table('products').select('id, name').eq('slug', 'collagen-3x-drops').single().execute()
product_id = product.data['id']

# Get an adaptation
adaptation = supabase.table('product_adaptations').select('*').eq('product_id', product_id).limit(1).execute()

if adaptation.data:
    adapt = adaptation.data[0]
    print('='*60)
    print('🎯 PRODUCT ADAPTATIONS')
    print('='*60)
    print()
    print('ADAPTATION SCORES')
    print('-'*60)
    print(f"  Hook Relevance: {adapt.get('hook_relevance_score', 'N/A')}/10")
    print(f"  Audience Match: {adapt.get('audience_match_score', 'N/A')}/10")
    print(f"  Transition Ease: {adapt.get('transition_ease_score', 'N/A')}/10")
    print(f"  Viral Replicability: {adapt.get('viral_replicability_score', 'N/A')}/10")
    print(f"  OVERALL SCORE: {adapt.get('overall_score', 'N/A')}/10")
    print()

    if adapt.get('adapted_hook'):
        print('ADAPTED HOOK')
        print('-'*60)
        print(adapt['adapted_hook'][:400])
        print('...' if len(adapt['adapted_hook']) > 400 else '')
        print()

    if adapt.get('adapted_script'):
        print('ADAPTED SCRIPT')
        print('-'*60)
        print(adapt['adapted_script'][:400])
        print('...' if len(adapt['adapted_script']) > 400 else '')
        print()
else:
    print('No adaptations found')
