import ast
import os
import numpy as np

def permutation_sign(a, b):
    """Compute the sign of the permutation that sends list a to list b."""
    # Map elements of a to their indices
    pos = {val: i for i, val in enumerate(a)}
    # Construct permutation indices
    perm = [pos[x] for x in b]
    # Compute parity of permutation
    inversions = sum(1 for i in range(len(perm)) for j in range(i+1, len(perm)) if perm[i] > perm[j])
    return -1 if inversions % 2 else 1

# Input and output files
input_file = os.environ["PRISMATOID_INPUT_FILE"]
orderedshifted_file = os.environ["PRISMATOID_OUTPUT_FILE"]
signs_dir = os.path.join(os.path.dirname(orderedshifted_file), "orientations")  # directory for individual sign files
os.makedirs(signs_dir, exist_ok=True)

counter = 1  # starts at 1

with open(input_file, "r", encoding="utf-8") as fin, \
     open(orderedshifted_file, "w", encoding="utf-8") as fout_orderedshifted:

    for line in fin:
        line = line.strip()
        if not line or line.startswith('-'):
            continue  # skip separator lines

        try:
            l_ori = ast.literal_eval(line)
        except Exception:
            print("Skipping invalid line:", line)
            continue

        l_sorted = [sorted(inner) for inner in l_ori]
        l_orderedshifted = [[x - 1 for x in lst] for lst in l_sorted]

        # Compute sign list for this line
        signs = [[i, permutation_sign(a, b)]
                 for i, (a, b) in enumerate(zip(l_ori, l_sorted))]

        # Write ordered/shifted data
        fout_orderedshifted.write(str(l_orderedshifted) + "\n")
        fout_orderedshifted.write(
            "------------------------------------------------------------------------------------------------\n"
        )

        # Write signs to an individual file
        signs_file = os.path.join(
            signs_dir, f"test_{counter}_orientation.txt"
        )
        with open(signs_file, "w", encoding="utf-8") as fout_signs:
            fout_signs.write(str(signs) + "\n")

        counter += 1

print(f"Ordered data saved to: {orderedshifted_file}")
print(f"{counter - 1} orientation files written to: {signs_dir}")
