import sys

base1= {str(i) for i in range(7)}; base2= {chr(97+i) for i in range(7)}
middle_facets= [set(line[:-1].split(" ")) for line in sys.stdin if len(line.split(" "))==5]
pris= [base1]+middle_facets+[base2]

# Calculo de distancias a la primera base
dists=[{0}]
for l in range(1,7):
    dists.append({i for i in set(range(len(pris))) - set.union(*dists[0:l])
                  if [j for j in dists[l-1] if len(pris[i]&pris[j])==4]})
#print("dists:", dists)
#print("\n")

def recursive_shelling(order, unused_facets, h_vector):
    if not unused_facets : return (order, h_vector)

    for i, f in enumerate(unused_facets):
        if len(order[-1]&base1)<len(f&base1): continue # preserve layers

        previousneighbors= [g for g in order if len(f&g)==4]
        newface= f - set.intersection(f, *previousneighbors)
        superfacets= [g for g in order if newface.issubset(g)]

        if not superfacets: #good
            new_order= list(order)+[f]
            new_unused_facets= list(unused_facets); new_unused_facets.pop(i)
            new_h_vector= list(h_vector); new_h_vector[len(previousneighbors)]+=1

            new_order, new_h_vector= recursive_shelling(new_order, new_unused_facets, new_h_vector)
            if new_order: return (new_order, new_h_vector)
    return ([],[])

s,h= recursive_shelling([base1], pris[1:-1],[0,0,0,0,0,0])

print("5", len(s)-1) # shelling of everything but the second base

for i,f in enumerate(s[1:],1):
    if len(f&base2)>len(pris[i-1]&base2): print("")
    print(*sorted(f))
