# **Specification: Structural Complexity Analysis (Nesting & Inheritance)**

## **1\. Overview**

Structural complexity analysis focuses on the internal logic flow and the hierarchical architecture of the code.

* **High Nesting Depth** identifies functions with excessive "if-else" or "loop" branching, which makes code difficult to read and test.  
* **Deep Inheritance** identifies class hierarchies that are too tall, leading to "fragile base class" problems where changes at the top have unpredictable effects at the bottom.

---

## **2\. Shared Pipeline Integration**

To minimize overhead, these analyses reuse the **Step 1: Scanning & AST Parsing** phase from the Brain File pipeline.

1. **Crawl:** The system visits every file in the module.  
2. **Parse:** The system generates a language-specific AST.  
3. **Dispatch:** Instead of just extracting imports/LOC, the AST is passed to two specialized "Visitors."

---

## **3\. Metric: High Nesting Depth**

This metric measures the maximum level of indentation caused by control flow statements within a single function or method.

### **A. The Logic**

A "Control Flow Node" is defined as any of the following:

* **Conditionals:** If, Else, Switch/Case.  
* **Loops:** For, While, Do-While.  
* **Error Handling:** Try/Catch (depending on language standards).

### **B. Technical Implementation (Visitor Pattern)**

1. **Initialization:** Set current\_depth \= 0 and max\_depth \= 0.  
2. **Traversal:**  
   * Upon entering a Control Flow Node $\\rightarrow$ current\_depth \+= 1.  
   * Update max\_depth \= max(max\_depth, current\_depth).  
   * Upon exiting the node $\\rightarrow$ current\_depth \-= 1.  
3. **Threshold:** If max\_depth \>= 4, flag the file with a **Complexity Penalty (+4)**.

---

## **4\. Metric: Deep Inheritance Relationship**

This metric measures the distance between a class and its furthest ancestor in the inheritance tree.

### **A. The Logic**

A relationship is considered "Deep" if a class is the result of multiple layers of derivation.

* **Example:** Object $\\rightarrow$ View $\\rightarrow$ Button $\\rightarrow$ IconButton $\\rightarrow$ RoundedIconButton (Depth: 4).

### **B. Technical Implementation (Global Map Approach)**

Inheritance often spans multiple files, so this requires a **Two-Pass Global Analysis**:

1. **Pass 1 (Extraction):** During the initial AST scan, extract every class name and its immediate parent(s).  
   * *Store in Database:* (class\_name, parent\_name, file\_id).  
2. **Pass 2 (Tree Walking):** After all files are scanned, reconstruct the chains.  
   * For each class, recursively find the parent until the "Root" (no parent) is found.  
   * **Calculation:** depth \= count\_nodes\_in\_chain \- 1.  
3. **Threshold:** If depth \>= 3, flag the file with an **Architectural Penalty (+4)**.

---

## **5\. Data Schema Integration**

The results are stored in the same file\_ownership\_metrics table, adding new columns to track structural health.

| Column | Type | Description |
| :---- | :---- | :---- |
| max\_nesting\_depth | Integer | The highest nesting level found in the file. |
| max\_inheritance\_depth | Integer | The longest inheritance chain for any class in the file. |
| structural\_risk\_score | Integer | The sum of penalties (e.g., \+4 for nesting, \+4 for depth). |

---

## **6\. Summary of Combined Pipeline**

By combining these with the Brain File analysis, the system performs a comprehensive "Health Check" in one go:

| Step | Brain File Task | Nesting Task | Inheritance Task |
| :---- | :---- | :---- | :---- |
| **1\. Parse** | Extract Imports | Identify Logic Blocks | Map Class Parents |
| **2\. Analyze** | Calculate Usage % | Walk Logic Trees | Trace Global Chains |
| **3\. Score** | Flag High-Usage \+ LOC | Check Depth $\\ge 4$ | Check Depth $\\ge 3$ |

