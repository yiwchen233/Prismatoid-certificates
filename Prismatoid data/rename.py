import sys

for i in range(1, int(sys.argv[1])):
    f=open("./sol"+str(i))
    g=open(str(i).zfill(4),"w+")

    for line in f:
        print(line, file=g, end='')

    f.close(); g.close()
