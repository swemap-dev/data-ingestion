# Skill Analysis

## 1. Build the graph
```python manage.py build_skill_graph conda```

## 2. Vectorize into FAISS
```python manage.py build_skill_vectors conda```

## 3. Test AST Source File
```
# --show-linearized prints the augmented S-expression for each code block before showing skill matches.

# Relative to backend/
python manage.py match_skills path/to/file.py --dataset conda --k 5 --show-linearized

# Absolute path
python manage.py match_skills /Users/justinchung/Code/SWEMAP/data-ingestion/playground/index.py --dataset conda --k 5
```