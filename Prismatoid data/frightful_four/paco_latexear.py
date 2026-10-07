from sys import stdin

base1= {str(i) for i in range(7)}
base2= {chr(97+i) for i in range(7)}
facets= [set(line[:-1].split(" ")) for line in stdin if len(line.split(" "))==5]

facets_by_layer=[[facet for facet in facets if len(facet&base2)==l] for l in range(0,5)]

column=0
print("%!TEX root = prismatoide.tex\n")
print("\prismatoide")
for l in range(1,5):
    print("% capa", l,":")
    print("{")

    for i in range(len(facets_by_layer[l])):
        if i%12==0 and i!=0: print("}{")
        print("    ", *sorted(facets_by_layer[l][i]), sep="", end=" \\\\\n")
        #to_print[i%18][column]="$"+"".join(sorted(facets_by_layer[l][i]))+"$"

    for i in range( (120-len(facets_by_layer[l]))%12 ):
        print("          \\\\")
    print("}")

#for i in range(18):
#    print(*to_print[i], sep=' & ', end=" //\n")
