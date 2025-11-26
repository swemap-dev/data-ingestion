#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>
#include <unordered_map>
#include <algorithm>
#include <cmath>
#include <omp.h>


struct TokenEdge {
    int token_id;
    double weight;
};

struct PairEntry {
    long long key;
    double value;
};

struct Pair {
    int t1, t2;
    double contrib;
};

// Comparator for sorting by (t1,t2)
struct PairComparator {
    bool operator()(const Pair& a, const Pair& b) const {
        return (a.t1 < b.t1) || (a.t1 == b.t1 && a.t2 < b.t2);
    }
};