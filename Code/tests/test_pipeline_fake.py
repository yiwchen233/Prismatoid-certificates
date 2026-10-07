from pathlib import Path
import json
import shutil

from prismatoid_batch.pipeline import BatchPipeline, PipelineOptions


FAKE_GUROBI = r'''
class Var:
    def __init__(self, name, lb=0.0, ub=1e100, vtype="C", obj=0.0):
        self.VarName=name; self.LB=lb; self.UB=ub; self.VType=vtype; self.Obj=obj; self.X=0.0

class Constr:
    def __init__(self, name, sense, rhs, coeffs):
        self.ConstrName=name; self.Sense=sense; self.RHS=rhs; self.coeffs=coeffs

class Row:
    def __init__(self, model, constr):
        self.items=[(model.by_name[name], value) for name,value in constr.coeffs.items()]
    def size(self): return len(self.items)
    def getVar(self, i): return self.items[i][0]
    def getCoeff(self, i): return self.items[i][1]

class Model:
    def __init__(self, name="model"):
        self.ModelName=name; self.vars=[]; self.by_name={}; self.constraints=[]
        self.SolCount=0; self.Status=1; self.ObjVal=0.0
        self.NumQConstrs=0; self.NumSOS=0; self.NumGenConstrs=0
    def addVar(self, lb=0.0, ub=1e100, vtype="C", obj=0.0, name=None):
        v=Var(name or f"x{len(self.vars)}",lb,ub,vtype,obj); self.vars.append(v); self.by_name[v.VarName]=v; return v
    def add_constraint(self, name, sense, rhs, coeffs):
        c=Constr(name,sense,rhs,coeffs); self.constraints.append(c); return c
    def update(self): pass
    def getVars(self): return list(self.vars)
    def getConstrs(self): return list(self.constraints)
    def getRow(self, c): return Row(self,c)
    def optimize(self, *args, **kwargs):
        x=self.by_name["x"]; y=self.by_name["y"]; z=self.by_name["z"]
        if x.LB <= .5 <= x.UB and y.LB <= .5 <= y.UB and z.LB <= 0 <= z.UB:
            x.X=.5; y.X=.5; z.X=0.; self.SolCount=1; self.Status=2
        else:
            self.SolCount=0; self.Status=3
'''

LEGACY = r'''
import gurobipy as gp
m=gp.Model("certificate")
x=m.addVar(lb=0,name="x")
y=m.addVar(lb=0,name="y")
z=m.addVar(lb=0,name="z")
m.add_constraint("normalization","=",1,{"x":1,"y":1,"z":1})
m.add_constraint("identity","=",0,{"x":1,"y":-1})
m.optimize()
if m.SolCount:
    print("certificate",x.X,y.X,z.X)
'''


def test_end_to_end_template_discovery(tmp_path):
    source_root = Path(__file__).resolve().parents[1]
    project = tmp_path / "project"
    project.mkdir()
    shutil.copytree(source_root / "prismatoid_batch", project / "prismatoid_batch")
    (project / "gurobipy.py").write_text(FAKE_GUROBI)
    entry = project / "legacy.py"
    entry.write_text(LEGACY)
    data = tmp_path / "data"
    data.mkdir()
    # Two valid prepared prismatoid-like facet files.
    (data / "0001").write_text("0 1 2\n3 4 5\n0 1 3 4\n")
    (data / "0002").write_text("0 1 2\n3 4 5\n0 2 3 5\n")
    output = tmp_path / "output"
    options = PipelineOptions(
        data_root=data,
        project_root=project,
        output_root=output,
        entrypoint=entry,
        prepare_mode="prepared",
        timeout=30,
        keep_sandboxes=False,
        template_first=True,
    )
    BatchPipeline(options).run()
    summary = (output / "summary.tsv").read_text()
    assert summary.count("certificate_exact") == 2
    library = json.loads((output / "templates" / "final_templates.json").read_text())
    assert len(library["templates"]) == 1
    assert sorted(library["templates"][0]["covered_candidates"]) == ["0001", "0002"]
    assert (output / "certificates" / "0001.txt").exists()
    assert (output / "certificates" / "0002.txt").exists()
    assert (output / "templates" / "individual" / "T0001.txt").exists()
