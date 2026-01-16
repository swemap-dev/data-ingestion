def risk_scores(table):
    """
    Description: Calculate (weighted) risk score for every engineer on the module
    Input: matrix -> columns: name, design, write, review | rows: n people
    Output: new matrix -> columns: name, weighted risk score | rows: n people
    """
    

    res = []
    for person in table:
        weighted_design = person[1] * 0.25
        weighted_write = person[2] * 0.50
        weighted_review = person[3] * 0.25
        score = weighted_design + weighted_write + weighted_review
        res.append([person[0], score])
    return res




def ownership(table):

    """
    Description: Calculate ownership % for every member on that module 
    Input: output from risk_scores
    Output: matrix -> columns: name, ownership percentage | rows: n people
    """

    res = []
    total = 0
    for person in table:
        total += person[1]
    for person in table:
        if total == 0:
            res.append([person[0], 0.0])
        else: 
            res.append([person[0], person[1] / total * 100])
    return res




def label(table):
    """
    Description: Give a risk label to the module (critical, high, medium or low) and attach 
    the top engineers that are the reason for the risk based on their ownership score
    Input: output from ownership
    Output: tuple(string, array) -> (risk level, n people with high ownership %s)
    """

    # Variables to keep track of engineers with highest ownership scores 
    high = ["", 0.0]
    higher = ["", 0.0]
    highest = ["", 0.0]

    # Find top engineers to populate prev variables
    for person in table:
        if highest[1] < person[1]:
            high[0], high[1] = higher[0], higher[1]
            higher[0], higher[1] = highest[0], highest[1]
            highest[0], highest[1] = person[0], person[1]
        elif higher[1] < person[1]:
            high[0], high[1] = higher[0], higher[1]
            higher[0], higher[1] = person[0], person[1]
        elif high[1] < person[1]:
            high[0], high[1] = person[0], person[1]

    # Calculate risk label - logic for critical and high risks is grounded in literature
    # Medium and low risk calculations are relative to critical/high risks
    if highest[1] >= 50.0:
        return ("Critical", highest)
    elif highest[1] + higher[1] >= 50.0:
        return ("High", highest, higher)
    elif highest[1] + higher[1] + high[1] >= 50.0:
        return ("Medium", highest, higher, high)
    else:
        return ("Low", highest, higher, high)