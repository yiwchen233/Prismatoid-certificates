"""One isolated flag attempt; all solver scratch files stay in a temporary directory."""
import sys, os, json, tempfile, logging
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from human_certificate import write_certificate, read_certificate, verify_bundle
from prismatoid_batch.facet_io import read_facets, looks_like_box_prismatoid, read_box_prismatoid
from prismatoid_batch.lp_solver import _build_equality_system, _solve_certificate_lp
import nonrealizability_certificate as core


class Search(core.NonRealizabilityTest):
    def solve_lp(self, matrix_fname=None, M=None):
        rows,cols,values=M
        by_column={}
        for r,c,v in zip(rows,cols,values):
            by_column.setdefault(int(c)-1,{})[int(r)-1]=int(v)
        count=max(map(int,rows)); columns=max(map(int,cols))
        A,b,_=_build_equality_system(column_count=columns,by_column=by_column,solve_rows=list(range(count)))
        result=_solve_certificate_lp(equality_matrix=A,rhs=b,variable_count=count,logger=self.logger)
        if not result.feasible:return '',np.array([],dtype=int)
        witness=self.accept_exact_solution(result.values)
        return 'exact',np.array([i for i,w in witness],dtype=int)


def main():
    source, output, cid, flag, seed, degree, factors, variant = sys.argv[1:]
    source=Path(source); F=[list(f) for f in read_facets(source).facets]
    labels=list(read_box_prismatoid(source).all_source_vertices) if looks_like_box_prismatoid(source) else None
    with tempfile.TemporaryDirectory(prefix='prismatoid-attempt-') as scratch:
        core.DIR_PATH=scratch
        try:
            test=Search(facets=F,dimension=5,file_name=cid,flag=flag,random_seed=int(seed),
                        max_deg=int(degree),n_factors=int(factors),language='sage',
                        gurobi_interface='sage',small_determinants='true' if variant=='all-variable-products-simplified' else 'false')
            result=test.run
            print('SELECTED_FLAG '+','.join(map(str,test.flag)),flush=True)
            if result==0:
                write_certificate(test.certificate_bundle,Path(output),labels)
                verify_bundle(read_certificate(Path(output)/'certificates'/f'{cid}.txt'),expected_facets=F)
                return 0
            return 2
        finally:
            logger=logging.getLogger('modules.logger')
            for handler in logger.handlers[:]:logger.removeHandler(handler);handler.close()

if __name__=='__main__':raise SystemExit(main())
