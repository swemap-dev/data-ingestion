import pytest
from oracle.blame.risk_score.risk_score import (risk_scores, ownership, label)

def test_risk_scores():
    
    # normal single person
    table1 = [
        ["Alice", 4, 6, 2]
    ]

    # normal multiple people
    table2 = [
        ["Alice", 4, 6, 2],
        ["Bob", 2, 4, 4],
        ["Charlie", 5, 5, 5]
    ]

    # zeroes
    table3 = [
        ["Alice", 0, 3, 0],
        ["Bob", 1, 0, 0]
    ]

    # floaters
    table4 = [
        ["Alice", 2.5, 3.5, 4.0],
        ["Bob", 1.2, 2.8, 3.6]
    ]

    #                                   === assert statements ===
    assert risk_scores(table1) == [
        ["Alice", 4*0.25 + 6*0.50 + 2*0.25]
    ]   

    assert risk_scores(table2) == [
        ["Alice",   4*0.25 + 6*0.50 + 2*0.25],
        ["Bob",     2*0.25 + 4*0.50 + 4*0.25],
        ["Charlie", 5*0.25 + 5*0.50 + 5*0.25]
    ]

    assert risk_scores(table3) == [
        ["Alice", 0*0.25 + 3*0.50 + 0*0.25],
        ["Bob",   1*0.25 + 0*0.50 + 0*0.25],
    ]

    assert risk_scores(table4) == [
        ["Alice", 2.5*0.25 + 3.5*0.50 + 4.0*0.25],
        ["Bob",   1.2*0.25 + 2.8*0.50 + 3.6*0.25],
    ]

    

def test_ownership():
    
    # single person 100%
    table1 = [
        ["Alice", 10.0]
    ]

    # multiple people 50/50 split
    table2 = [
        ["Alice", 5.0],
        ["Bob", 5.0]
    ]

    # multiple people uneven split
    table3 = [
        ["Alice", 7.5],
        ["Bob", 2.5]
    ]

    # multiple people rounding
    table4 = [
        ["Alice", 1.0],
        ["Bob", 2.0],
        ["Charlie", 3.0]
    ]

    # multiple people zero total
    table5 = [
        ["Alice", 0.0],
        ["Bob", 0.0]
    ]

    # single person zero total
    table6 = [
        ["Alice", 0.0]
    ]

    #                                   === assert statements ===

    assert ownership(table1) == [
        ["Alice", 100.0]
    ]

    assert ownership(table2) == [
        ["Alice", 50.0],
        ["Bob", 50.0]
    ]

    assert ownership(table3) == [
        ["Alice", 75.0],
        ["Bob", 25.0]
    ]

    assert ownership(table4) == [
        ["Alice", 1.0/6.0 * 100],
        ["Bob", 2.0/6.0 * 100],
        ["Charlie", 50.0]
    ]

    assert ownership(table5) == [
        ["Alice", 0.0],
        ["Bob", 0.0]
    ]

    assert ownership(table6) == [
        ["Alice", 0.0]
    ]

def test_label():

    # multiple people high
    table1 = [
        ["Alice", 75.0],
        ["Bob", 25.0]
    ]

    # multiple people split
    table2 = [
        ["Alice", 50.0],
        ["Bob", 50.0]
    ]

    # multiple people different splits
    table3 = [
        ["Alice", 30.0],
        ["Bob", 25.0],
        ["Charlie", 45.0]
    ]

    # many people even split
    table4 = [
        ["Alice", 20.0],
        ["Bob", 20.0],
        ["Charlie", 20.0],
        ["Dana", 20.0],
        ["Eve", 20.0]
    ]

    # 3 people (almost) same split
    table5 = [
        ["Alice", 33.33],
        ["Bob", 33.33],
        ["Charlie", 33.34]
    ]

    # many people even split
    table6 = [
        ["Alice", 25.0],
        ["Bob", 25.0],
        ["Charlie", 25.0],
        ["Dana", 25.0],
    ]

    # Many many people 
    table7 = [
        ["Alice", 12.5],
        ["Bob", 12.5],
        ["Charlie", 12.5],
        ["Dana", 12.5],
        ["Eve", 12.5],
        ["Frank", 12.5],
        ["Grace", 12.5],
        ["Heidi", 12.5],
    ]

    #                                   === assert statements ===


    assert label(table1) == (
        "Critical",
        ["Alice", 75.0]
    )

    assert label(table2) == (
        "Critical",
        ["Alice", 50.0]
    )

    assert label(table3) == (
        "High",
        ["Charlie", 45.0],
        ["Alice", 30.0]
    )

    assert label(table4) == (
        "Medium",
        ["Alice", 20.0],
        ["Bob", 20.0],
        ["Charlie", 20.0]
    )

    assert label(table5) == (
        "High",
        ["Charlie", 33.34],
        ["Alice", 33.33]
    )

    assert label(table6) == (
        "High",
        ["Alice", 25.0],
        ["Bob", 25.0]
    )

    assert label(table7) == (
        "Low",
        ["Alice", 12.5],
        ["Bob", 12.5],
        ["Charlie", 12.5]
    )

