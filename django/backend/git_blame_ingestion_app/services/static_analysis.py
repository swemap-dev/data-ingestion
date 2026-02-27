import logging
import tree_sitter_python
import tree_sitter_javascript
from tree_sitter import Language, Parser, Node

logger = logging.getLogger(__name__)

# Initialize singletons for Languages
PY_LANGUAGE = Language(tree_sitter_python.language())
JS_LANGUAGE = Language(tree_sitter_javascript.language())

def _walk_python_imports(node: Node, imports: set):
    if node.type == 'import_statement':
        for child in node.children:
            if child.type == 'dotted_name':
                imports.add(child.text.decode('utf-8'))
    elif node.type == 'import_from_statement':
        # module_name is typically the first dotted_name or relative_import
        for child in node.children:
            if child.type in ('dotted_name', 'relative_import'):
                imports.add(child.text.decode('utf-8'))
                break # only want the from part, not what's imported

    for child in node.children:
        _walk_python_imports(child, imports)


def parse_python(source_code: bytes) -> dict:
    parser = Parser(PY_LANGUAGE)
    tree = parser.parse(source_code)
    
    # Calculate non-comment LOC
    lines = source_code.split(b'\n')
    loc = 0
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith(b'#'):
            loc += 1
            
    imports = set()
    _walk_python_imports(tree.root_node, imports)
        
    return {
        "loc": loc,
        "imports": list(imports)
    }


def _walk_js_imports(node: Node, imports: set):
    if node.type == 'import_statement':
        for child in node.children:
            if child.type == 'string':
                val = child.text.decode('utf-8').strip("'\"")
                imports.add(val)
                
    elif node.type == 'call_expression':
        # Check for require("something")
        is_require = False
        for child in node.children:
            if child.type == 'identifier' and child.text == b'require':
                is_require = True
            elif is_require and child.type == 'arguments':
                for arg in child.children:
                    if arg.type == 'string':
                        val = arg.text.decode('utf-8').strip("'\"")
                        imports.add(val)

    for child in node.children:
        _walk_js_imports(child, imports)


def parse_javascript(source_code: bytes) -> dict:
    parser = Parser(JS_LANGUAGE)
    tree = parser.parse(source_code)
    
    lines = source_code.split(b'\n')
    loc = 0
    in_block = False
    for line in lines:
        stripped = line.strip()
        if not in_block:
            if stripped.startswith(b'/*'):
                if not b'*/' in stripped:
                    in_block = True
            elif stripped and not (stripped.startswith(b'//')):
                loc += 1
        else:
            if b'*/' in stripped:
                in_block = False
                
    imports = set()
    _walk_js_imports(tree.root_node, imports)
        
    return {
        "loc": loc,
        "imports": list(imports)
    }


def analyze_code_file(file_path: str, source_code: bytes) -> dict:
    """
    Analyzes the source code to extract LOC and imports (dependencies).
    If the language is unsupported, it returns a basic LOC count.
    """
    if file_path.endswith('.py'):
        return parse_python(source_code)
    elif file_path.endswith(('.js', '.jsx', '.ts', '.tsx')):
        return parse_javascript(source_code)
    else:
        # Fallback basic LOC
        lines = source_code.split(b'\n')
        loc = len([l for l in lines if l.strip()])
        return {"loc": loc, "imports": []}

