#include <nlohmann/json.hpp>

using json = nlohmann::json;
using EdgeMap = std::unordered_map<long long, int>;

struct Edge {
    int file_id;
    int token_id;
    int weight;  // number of times token appears in this file
};

EdgeMap build_edge_map_par(std::unordered_map<std::string, int>& token_to_id,
                           std::unordered_map<std::string, int> file_to_id,
                           std::vector<std::string>& id_to_token, json j);

EdgeMap build_edge_map_par(std::unordered_map<std::string, int>& token_to_id,
                           std::unordered_map<std::string, int> file_to_id,
                           std::vector<std::string>& id_to_token, json j);