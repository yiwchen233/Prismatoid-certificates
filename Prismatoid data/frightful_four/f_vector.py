import sys

the_file= open(sys.argv[1])
middle_facets= [set(line[:-1].split(" ")) for line in the_file if len(line.split(" "))==5]
pris= middle_facets

f_vector= [0 for _ in range(6)]
faces=set()
for f in pris:
    L=list(f)
    subs = [frozenset({L[j] for j in range(len(L)) if 1<<j&i}) for i in range(1,1<<len(L))]
    faces= faces|set(subs)

f_vector= [ len([f for f in faces if len(f)==s]) for s in range(6)]
print(f_vector)
