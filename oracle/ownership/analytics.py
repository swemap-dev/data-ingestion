import psycopg
import os
import dotenv
from typing import List, Tuple

dotenv.load_dotenv()
DB_DSN = os.getenv("DB_DSN")

def get_review_percentage_of_file(file_id: int) -> List[Tuple[str, float]]:
    """
    Calculates the percentage of lines reviewed by each engineer for a specific file.
    
    Args:
        file_id (int): The ID of the file to analyze.
        
    Returns:
        List[Tuple[str, float]]: A list of tuples (reviewer_name, percentage) 
                                 sorted in decreasing order of percentage.
    """
    try:
        with psycopg.connect(DB_DSN) as conn:
            with conn.cursor() as cur:
                # 1. Get total lines in the file
                cur.execute("SELECT line_count FROM files WHERE id = %s", (file_id,))
                res = cur.fetchone()
                if not res:
                    print(f"File with ID {file_id} not found.")
                    return []
                
                total_lines = res[0]
                if not total_lines or total_lines == 0:
                    return []

                # 2. Query Pre-calculated Metrics
                cur.execute("""
                    SELECT 
                        e.name,
                        fom.lines_owned_percentage
                    FROM file_ownership_metrics fom
                    JOIN engineers e ON fom.engineer_id = e.id
                    WHERE fom.file_id = %s AND fom.type = 'REVIEWED'
                """, (file_id,))
                
                results = []
                for row in cur.fetchall():
                    reviewer_name = row[0]
                    percentage = row[1]
                    results.append((reviewer_name, percentage))
                
                # Sort by percentage descending
                results.sort(key=lambda x: x[1], reverse=True)
                
                return results

    except Exception as e:
        print(f"Error calculating review percentage: {e}")
        return []

if __name__ == "__main__":
    print(get_review_percentage_of_file(91))