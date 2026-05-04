import os
import django

# 1. Point to your Django settings
# This step is CRITICAL and must happen before you import any Django models or services
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

# 2. Boot up Django
django.setup()

# 3. NOW you can safely import your function
from django.conf import settings
from skill_analysis.services.code_skill_matcher import get_engineer_files, CodeSkillMatcher
from skill_analysis.services.cso_vectorizer import CSOVectorizer

REPO_ROOT = "/Users/justinchung/Code/SWEMAP/conda"

if __name__ == '__main__':
    # 4. Get the files for the engineer
    files = get_engineer_files(3424)
    print(f"Found {len(files)} files for engineer. Loading vector index...")
    
    # 5. Initialize the FAISS index just ONCE
    config = settings.SKILL_DATASETS['conda']
    index, mapping = CSOVectorizer.load(config['index_path'], config['mapping_path'])
    matcher = CodeSkillMatcher(index, mapping)
    
    all_results = []
    total_functions_analyzed = 0
    
    # 6. Loop through files and analyze
    for rel_path in files:
        full_path = os.path.join(REPO_ROOT, rel_path)
        
        # Skip files that might not exist locally
        if not os.path.exists(full_path):
            continue
            
        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
            source_code = f.read()
            
        # Run the pipeline to get per-block skills
        # MAKE SURE max_length in code_skill_matcher.py is set back to 512!
        file_results = matcher.match_file(source_code, k=5, mode='raw')
        all_results.extend(file_results)
        total_functions_analyzed += len(file_results)
        
    print(f"\nAnalyzed {total_functions_analyzed} functions across {len(files)} files.")
    
    # 7. Aggregate all blocks across all files for this engineer
    if all_results:
        engineer_top_skills = CodeSkillMatcher.aggregate(all_results, k=10, pool="max")
        print("\n--- Top 10 Aggregated Skills for Engineer ---")
        for uri, score in engineer_top_skills:
            # Clean up the URI for display
            label = uri.rsplit('/', 1)[-1] if '/' in uri else uri
            print(f"  {label:40s} (score={score:.4f})")
    else:
        print("\nNo code functions found to aggregate.")