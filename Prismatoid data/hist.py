import matplotlib.pyplot as plt

thefile= open("index")

vfs= {}
data=[[] for i in range(29)]
h=[]

for line in thefile:
    (_,i,_,_,v,_,_)= line.split()
    i=int(i)
    v=int(v)

    g= open(str(i).zfill(4))
    f= int(g.readline().split()[1])
    g.close()

    data[v].append(f)
    h.append(v)

    if (v,f) not in vfs:
        vfs[(v,f)]=1
    else:
        vfs[(v,f)]+=1

vs=[]; fs=[]; cs=[]
for (v,f), c in vfs.items():
    vs.append(v)
    fs.append(f)
    cs.append(c)


#plt.scatter(vs, fs, s=cs, alpha=0.5)
f, (a0, a1) = plt.subplots(2,1, gridspec_kw = {'height_ratios':[1,3]})
a0.bar(range(14,29), [len(a) for a in data[14:]])
a1.violinplot(data[14:], range(14,29))

f.tight_layout()
f.savefig('grid_figure.png')
plt.show()
