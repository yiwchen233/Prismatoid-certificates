import ast
import os
import re

input_file = os.environ["PRISMATOID_INPUT_FILE"]
output_file = os.environ["PRISMATOID_OUTPUT_FILE"]
with open(input_file, "r", encoding="utf-8") as f:
    raw = f.read()
blocks = [b.strip() for b in re.split(r"\n\s*-{2,}\s*\n", raw) if b.strip()]

with open(output_file, "w", encoding="utf-8") as f:
    for bi, block in enumerate(blocks):
        l = ast.literal_eval(block)
        
        res = []
        for i in l:
            i = sorted(i)
            resi = []
            for j in i:
                resi.append(j - 1)
            res.append(resi)
        f.write(str(res))

        if bi != len(blocks) - 1:
            f.write("\n------------------------------------------------------------------------------------------------\n")