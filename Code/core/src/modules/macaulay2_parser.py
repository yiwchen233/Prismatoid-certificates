import os

def fix_m2_list(m2_list_str):
    """
    Fix the Macaulay2 list string to be a valid one for Sage {} -> [].

    :param m2_list_str: str, Macaulay2 list
    :return str, Python list
    """
    return m2_list_str.replace('{', '[').replace('}', ']')

def sage_orientation(file_name, redundant_facets="false"):
    """
    Read orientation file provided.

    :param file_name: str, file name prefix
    :param redundant_facets: boolean, true if we want to keep all facet bases for each nonsimplicial facets
    :return dict, list of tuples, a tuple representing the column index and orientation (1 or -1) ex. (34, -1)
    """
    if redundant_facets == "true":
        orientation_file_name = file_name + "_orientation_redundant_facets.txt"
    else:
        orientation_file_name = file_name + "_orientation.txt"

    if not os.path.isfile(orientation_file_name):
        return dict()

    with open(orientation_file_name, "r") as myfile:
        m2_orientation_str = myfile.read().rstrip('\n')

    return dict(eval(fix_m2_list(m2_orientation_str)))
