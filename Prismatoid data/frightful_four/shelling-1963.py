a=10;b=11;c=12;d=13;e=14;f=15;g=16;h=17
pris0=[ [0,1,2,3,4],[0,1,2,4,5],[0,1,2,5,6] ] # todos distancia 0, por definicion

pris1=[ [0,1,2,3  ,  d],  # tipo 1 y distancia 1
        [1,2,3,4  ,  g],
        [0,2,3,4  ,  g],
        [0,1,3,4  ,  g],
        [1,2,4,5  ,  f],
        [0,2,4,5  ,  f],
        [0,1,4,5  ,  f],
        [1,2,5,6  ,  e],
        [0,2,5,6  ,  e],
        [0,1,5,6  ,  e],
        [0,1,2,6  ,  d]]  # faceta n 13
pris2=[ [1,2,3  ,  c,d],  # tipo 2 y distancia 2
        [1,2,3  ,  c,g],  # "
        [0,2,3  ,  c,g],  # "
        [0,2,3  ,  b,d],  # "
        [0,1,3  ,  b,d],  # "
        [1,2,4  ,  c,g],  # "
        [0,2,4  ,  a,f],  # "
        [0,2,4  ,  c,g],  # "
        [0,1,3  ,  b,g],  # "
        [1,2,4  ,  c,f],  # "
        [0,1,4  ,  c,g],  # "
        [0,1,4  ,  c,f],  # "
        [0,2,5  ,  a,f],  # "
        [0,2,6  ,  b,d],  # "
        [1,2,5  ,  a,f],  # "
        [0,2,5  ,  a,e],  # "
        [0,1,5  ,  a,f],  # "
        [0,2,6  ,  b,e],  # "
        [0,1,6  ,  b,d],  # "  faceta n 32
        [0,1,5  ,  a,e],  # "
        [1,2,6  ,  b,d],  # "
        [1,2,6  ,  b,e],  # "
        [0,1,6  ,  a,e],  # "
        [1,2,5  ,  b,e],  # "
       #
        [0,2,3  ,  b,e], # tipo 2 y distancia 3
        [0,2,4  ,  a,e], # tipo 2 y distancia 3
        [1,2,5  ,  b,d], # tipo 2 y distancia 3
        [0,2,3  ,  c,e], # tipo 2 y distancia 3
        [0,2,4  ,  c,e], # tipo 2 y distancia 3
        [1,2,5  ,  c,d], # tipo 2 y distancia 3
        [0,1,6  ,  a,f], # tipo 2 y distancia 3
        [0,1,6  ,  b,g], # tipo 2 y distancia 3 
        [1,2,5  ,  a,c], # tipo 2 y distancia 3
        [0,1,6  ,  c,f], # tipo 2 y distancia 3
        [0,1,6  ,  c,g]] # tipo 2 y distancia 3 # faceta n 48
       
pris3=[
       [1,3  ,  b,c,d], # tipo 3 y distancia 3
       [2,3  ,  b,c,d], # tipo 3 y distancia 3
       [0,6  ,  a,b,e], # tipo 3 y distancia 3
       [1,6  ,  a,b,e], # tipo 3 y distancia 3
       [1,5  ,  a,b,e], # tipo 3 y distancia 3
       [2,5  ,  a,b,e], # tipo 3 y distancia 3
       [1,2  ,  a,c,f], # tipo 3 y distancia 3
       [2,4  ,  a,c,f], # tipo 3 y distancia 3
       [1,3  ,  b,c,g], # tipo 3 y distancia 3
       [0,4  ,  a,c,f], # tipo 3 y distancia 3
       [0,3  ,  b,c,g], # tipo 3 y distancia 3 # faceta n 59
       #
       [1,5  ,  b,c,d], # tipo 3 y distancia 4
       [2,5  ,  a,c,d], # tipo 3 y distancia 4
       [2,5  ,  a,b,d], # tipo 3 y distancia 4
       [2,3  ,  b,c,e], # tipo 3 y distancia 4
       [2,4  ,  a,c,d], # tipo 3 y distancia 4
       [2,4  ,  b,c,e], # tipo 3 y distancia 4
       [0,4  ,  a,c,e], # tipo 3 y distancia 4
       [0,3  ,  a,b,e], # tipo 3 y distancia 4
       [2,4  ,  a,b,e], # tipo 3 y distancia 4
       [1,6  ,  a,c,f], # tipo 3 y distancia 4
       [0,6  ,  a,b,f], # tipo 3 y distancia 4
       [0,6  ,  b,c,g], # tipo 3 y distancia 4
       [1,5  ,  b,c,g], # tipo 3 y distancia 4
       [2,4  ,  b,c,d], # tipo 3 y distancia 4
       [0,3  ,  a,c,e], # tipo 3 y distancia 4
       [0,6  ,  b,c,f], # tipo 3 y distancia 4
       [1,6  ,  a,c,g], # tipo 3 y distancia 4
       [1,5  ,  a,c,g], # tipo 3 y distancia 4
       [1,6  ,  a,b,g], # tipo 3 y distancia 4
       [0,3  ,  b,c,f], # tipo 3 y distancia 4
       [1,5  ,  a,b,g], # tipo 3 y distancia 4
       [0,3  ,  a,c,f], # tipo 3 y distancia 4
       # faceta 81
       [2,4  ,  a,b,d], # tipo 3 y distancia 5
       [0,3  ,  a,b,f]] # tipo 3 y distancia 5


pris4=[ [5  ,  a,b,c,d], # tipo 4 y distancia 5
       [4  ,  b,c,d,e], # tipo 4 y distancia 5
       [4  ,  a,c,d,e], # tipo 4 y distancia 5
       [4  ,  a,b,d,e], # tipo 4 y distancia 5
       [3  ,  b,c,e,f], # tipo 4 y distancia 5
       [3  ,  a,c,e,f], # tipo 4 y distancia 5
       [3  ,  a,b,e,f], # tipo 4 y distancia 5
       [6  ,  b,c,f,g], # tipo 4 y distancia 5
       [6  ,  a,c,f,g], # tipo 4 y distancia 5
       [6  ,  a,b,f,g], # tipo 4 y distancia 5
       [5  ,  a,b,c,g]     ] # tipo 4 y distancia 5

pris5=[[a,b,c,d,e], [a,b,c,e,f], [a,b,c,f,g]] # tipo 5 y distancia 6

pris = pris0 + pris1 + pris2 + pris3 + pris4 + pris5
#print(pris)

def neighbors(n):
    #print(pris[n])
    lista=[]
    for i in range(len(pris)):
        if len(set(pris[i]) & set(pris[n]))==4:
            lista.append(i)
    #print(lista)
    #print([pris[i] for i in lista])
    return set(lista)

# Calculo de distancias a la primera base

dist0=set(range(3))
print('A distancia 0:',dist0)

dist1=set()
for facet in dist0:
    dist1=dist1|neighbors(facet)
dist1= dist1 - dist0
print('A distancia 1:',dist1)

dist2=set()
previous=dist0|dist1
for facet in previous:
    dist2=dist2|neighbors(facet)
dist2= dist2 - previous
print('A distancia 2:',dist2)

dist3=set()
previous=dist0|dist1|dist2
for facet in previous:
    dist3=dist3|neighbors(facet)
dist3= dist3 - previous
print('A distancia 3:',dist3)

dist4=set()
previous=dist0|dist1|dist2|dist3
for facet in previous:
    dist4=dist4|neighbors(facet)
dist4= dist4 - previous
print('A distancia 4:',dist4)

dist5=set()
previous=dist0|dist1|dist2|dist3|dist4
for facet in previous:
    dist5=dist5|neighbors(facet)
dist5= dist5 - previous
print('A distancia 5:',dist5)

dist6=set()
previous=dist0|dist1|dist2|dist3|dist4|dist5
for facet in previous:
    dist6=dist6|neighbors(facet)
dist6= dist6 - previous
print('A distancia 6:',dist6)

print()
print()


# Calculo del h-vector( suponiendo que el orden sea shelling)
# Explicacion: si el orden es un shelling,
# la faceta n contribuye al h_i tal que i vecinos de n vienen antes de n, y 5-i vecinos vienen despues
h=[0,0,0,0,0,0]

# check shelling until error found
firsterror=len(pris)
for n in range(len(pris)):
    count=0
    oldface=set(pris[n])
    for m in neighbors(n):
        if m<n:
            count=count+1
            oldface=oldface&set(pris[m])
    h[count]=h[count]+1
    newface=set(pris[n]) - oldface
    facetisgood=1
    superface=set()
    for m in range(n):
        if newface.issubset(set(pris[m])):
            superface=superface|set([m])
            facetisgood=0
    if facetisgood==0:            
            print(n,sorted(pris[n]),'index',count,'; new face',sorted(newface),'; neighbors',neighbors(n),'; ERROR')
            print(n,'    !!!!! The newface was part of facets',superface)
            firsterror=n
            break
    if facetisgood==1:
        print(n,sorted(pris[n]),'index',count,'; new face',sorted(newface),'; neighbors',neighbors(n),'; ALL CORRECT')

print()
if firsterror != len(pris):
    print('Now I will search for a new facet')
else:
    print('BINGO. WE HAVE A SHELLING. ITS h-VECTOR IS', h)

# search for new facet
for n in range(firsterror,len(pris)): 
    count=0
    oldface=set(pris[n])
    for m in neighbors(n):
        if m<firsterror:
            count=count+1
            oldface=oldface&set(pris[m])
    h[count]=h[count]+1
    newface=set(pris[n]) - oldface
    facetisgood=1
    superface=set()
    for m in range(firsterror):
        if newface.issubset(set(pris[m])):
            superface=superface|set([m])
            facetisgood=0
    if facetisgood==0:            
            print(n,sorted(pris[n]),count,sorted(newface),neighbors(n),h)
            print(n,'ERROR. The newface',newface,'is part of facets',superface)
    if facetisgood==1:
        print(n,sorted(pris[n]),count,sorted(newface),neighbors(n),h,' CAN BE ADDED')

# Calculo de las facetas con 'tipo = distancia'

#tight = level0 | (level1&dist1)  | (level2&dist2) | (level3 & dist3)  | (level4 & dist4) | (level5 & dist5)
#notight = (level1-dist1)  | (level2-dist2) | (level3 - dist3)  | (level4 - dist4) | (level5 - dist5)
#print(tight)
#print(notight)

#bola1=[pris[i] for i in tight]
#bola2=[pris[i] for i in notight]
#print(bola1)
#print(bola2)
