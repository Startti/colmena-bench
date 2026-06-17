from demo05_loc import count_loc


def test_counts_code_lines_ignores_blank_and_comments(tmp_path):
    p = tmp_path / "h.py"
    p.write_text(
        "# a comment\n"
        "\n"
        "import os\n"
        "x = 1  # trailing\n"
        "    # indented comment\n"
        "y = 2\n"
    )
    assert count_loc(p) == 3  # import os / x = 1 / y = 2


def test_json_counts_nonblank_lines(tmp_path):
    p = tmp_path / "dag.json"
    p.write_text('{\n  "a": 1,\n\n  "b": 2\n}\n')
    assert count_loc(p) == 4


def test_docstrings_are_not_counted(tmp_path):
    p = tmp_path / "h.py"
    p.write_text(
        '"""Module docstring line 1.\n'
        "line 2.\n"
        'line 3."""\n'
        "import os\n"
        "def f():\n"
        '    """One-line function docstring."""\n'
        "    return 1\n"
    )
    # import os / def f(): / return 1 == 3; both docstrings excluded
    assert count_loc(p) == 3
