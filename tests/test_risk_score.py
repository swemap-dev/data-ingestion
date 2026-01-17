import pytest
from oracle.risk_score.risk_score import (risk_scores, ownership, label)

@pytest.mark.parametrize(
    "table, expected",
    [   
        # normal single person
        (
            [["Alice", 4, 6, 2]],
            [["Alice", 4*0.25 + 6*0.50 + 2*0.25]],
        ),

        # normal multiple people
        (
            [
                ["Alice", 4, 6, 2],
                ["Bob", 2, 4, 4],
                ["Charlie", 5, 5, 5],
            ],
            [
                ["Alice", 4*0.25 + 6*0.50 + 2*0.25],
                ["Bob", 2*0.25 + 4*0.50 + 4*0.25],
                ["Charlie", 5*0.25 + 5*0.50 + 5*0.25],
            ],
        ),

        # zeroes
        (
            [["Alice", 0, 3, 0], ["Bob", 1, 0, 0]],
            [
                ["Alice", 0*0.25 + 3*0.50 + 0*0.25],
                ["Bob", 1*0.25 + 0*0.50 + 0*0.25],
            ],
        ),

        # floaters
        (
            [["Alice", 2.5, 3.5, 4.0], ["Bob", 1.2, 2.8, 3.6]],
            [
                ["Alice", 2.5*0.25 + 3.5*0.50 + 4.0*0.25],
                ["Bob", 1.2*0.25 + 2.8*0.50 + 3.6*0.25],
            ],
        ),
    ],
)

def test_risk_scores(table, expected):
    """
    Parametrized test for the `risk_scores` function.

    Each test case includes:
    - "table": a list of [person, score1, score2, score3] entries
    - "expected": the expected weighted score for each person

    This test ensures that `risk_scores` correctly:
    - Applies weighted averages to multiple columns
    - Handles single and multiple people
    - Works with zero values and floating point numbers
    - Computes expected risk scores accurately

    Pytest will automatically run this test for each tuple in the parametrize list.
    """
    assert risk_scores(table) == expected


@pytest.mark.parametrize(
    "table, expected",
    [   
        # single person 100%
        (
            [
                ["Alice", 10.0]
            ], 
            [
                ["Alice", 100.0]
            ]
        ),

        # multiple people 50/50 split
        (
            [
                ["Alice", 5.0], 
                ["Bob", 5.0]
            ], 
            [
                ["Alice", 50.0], 
                ["Bob", 50.0]
            ]
        ),

        # multiple people uneven split
        (   
            [
                ["Alice", 7.5], 
                ["Bob", 2.5]
            ], 
            [
                ["Alice", 75.0], 
                ["Bob", 25.0]
            ]
        ),

        # multiple people rounding
        (
            [
                ["Alice", 1.0], 
                ["Bob", 2.0], 
                ["Charlie", 3.0]
            ],
            [
                ["Alice", 1.0 / 6.0 * 100],
                ["Bob", 2.0 / 6.0 * 100],
                ["Charlie", 50.0],
            ],
        ),

        # multiple people zero total
        (
            [
                ["Alice", 0.0], 
                ["Bob", 0.0]
            ], 
            [
                ["Alice", 0.0], 
                ["Bob", 0.0]
            ]
        ),

        # single person zero total
        (
            [
                ["Alice", 0.0]
            ], 
            [
                ["Alice", 0.0]
            ]
        ),
    ],
)

def test_ownership(table, expected):
    """
    Parametrized test for the `ownership` function.

    Each test case includes:
    - "table": a list of [person, value] pairs
    - "expected": the expected normalized ownership percentages

    This test checks that `ownership` correctly:
    - Converts raw values into percentages
    - Handles single and multiple people
    - Deals with zero totals and rounding
    - Ensures the sum of percentages is correct

    Pytest will automatically run this test for each tuple in the parametrize list.
    """
    assert ownership(table) == expected


@pytest.mark.parametrize(
    "table, expected",
    [
        # Multiple people, one high value
        (
            [["Alice", 75.0], ["Bob", 25.0]],
            ("Critical", ["Alice", 75.0]),
        ),

        # Multiple people, split evenly between two
        (
            [["Alice", 50.0], ["Bob", 50.0]],
            ("Critical", ["Alice", 50.0]),
        ),

        # Multiple people, uneven split
        (
            [["Alice", 30.0], ["Bob", 25.0], ["Charlie", 45.0]],
            ("High", ["Charlie", 45.0], ["Alice", 30.0]),
        ),

        # Many people, even split
        (
            [["Alice", 20.0], ["Bob", 20.0], ["Charlie", 20.0], ["Dana", 20.0], ["Eve", 20.0]],
            ("Medium", ["Alice", 20.0], ["Bob", 20.0], ["Charlie", 20.0]),
        ),

        # Three people, nearly equal split
        (
            [["Alice", 33.33], ["Bob", 33.33], ["Charlie", 33.34]],
            ("High", ["Charlie", 33.34], ["Alice", 33.33]),
        ),

        # Four people, equal split
        (
            [["Alice", 25.0], ["Bob", 25.0], ["Charlie", 25.0], ["Dana", 25.0]],
            ("High", ["Alice", 25.0], ["Bob", 25.0]),
        ),

        # Many people, small equal splits
        (
            [
                ["Alice", 12.5],
                ["Bob", 12.5],
                ["Charlie", 12.5],
                ["Dana", 12.5],
                ["Eve", 12.5],
                ["Frank", 12.5],
                ["Grace", 12.5],
                ["Heidi", 12.5],
            ],
            ("Low", ["Alice", 12.5], ["Bob", 12.5], ["Charlie", 12.5]),
        ),
    ],
)

def test_label(table, expected):
    """
    Parametrized test for 'label' function.
    
    Each test case includes:
    - "table": a list of [person, score] pairs
    - "expected": the expected output from `label`

    Pytest will automatically run this test for each tuple in the parametrize list.
    """
    assert label(table) == expected