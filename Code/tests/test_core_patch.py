"""Tests invoke the actual patched class, not a fake NonRealizabilityTest."""
import copy,json,random,sys,tempfile,unittest,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CODE=Path(os.getenv('PRISMATOID_TEST_CODE_ROOT',str(ROOT/'core')))
BATCH=Path(os.getenv('PRISMATOID_TEST_BATCH_ROOT',str(ROOT)))
sys.path[:0]=[str(CODE/'src'),str(BATCH)]
from nonrealizability_certificate import NonRealizabilityTest,HAVE_SAGE
from modules import certificate_geometry as g
from modules.exact_polynomial import ExactRing,to_ring,from_ring
from modules.verify_certificate import verify_bundle
from prismatoid_batch.flag_search import sample_rank_certified_facet_flags
from prismatoid_batch.cli import build_parser
from prismatoid_batch.sage_solver_adapter import _sparse_coordinates
INPUT=ROOT/'examples/prepared/0213.txt'
F=[list(map(int,l.split())) for l in INPUT.read_text().splitlines() if l.strip()]
class PatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        import nonrealizability_certificate as core
        cls.old_dir=core.DIR_PATH;core.DIR_PATH=cls.tmp.name
    @classmethod
    def tearDownClass(cls):
        import nonrealizability_certificate as core
        import logging
        logger = logging.getLogger('modules.logger')
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()
        core.DIR_PATH=cls.old_dir;cls.tmp.cleanup()
    def test_cli_default_twenty_flags(self):
        args=build_parser().parse_args(['run','--data','/tmp/data','--output','/tmp/output'])
        self.assertEqual(args.flag_attempts,20)
    def test_rank_requires_actual_triangular_minor(self):
        self.assertIsNone(g.rank_witness([[1,1],[1,1]]))
        self.assertIsNotNone(g.rank_witness([[1,0],[1,1]]))
    def test_sampler_distinct_and_includes_bases(self):
        flags=sample_rank_certified_facet_flags(F,5,20,random_seed=0,candidate_id='anything')
        self.assertEqual(len(flags),20)
        self.assertEqual(len({frozenset(f) for f in flags}),20)
        for f in flags:
            self.assertEqual(len(f),6);self.assertTrue({0,1}.issubset(f));self.assertIsNotNone(g.flag_witness(F,f))
    def test_plain_polynomial_roundtrip_and_products(self):
        R=ExactRing(['x','y']);x,y=R.gens();p=x*x+2*x*y-y+1
        self.assertEqual(from_ring(to_ring(R,from_ring(p))),from_ring(p))
        self.assertEqual(p.degree(),2)
        self.assertEqual((p*p).degree(),4)
    @unittest.skipUnless(HAVE_SAGE,'Sage is not installed in this environment')
    def test_sage_polynomial_roundtrip(self):
        from sage.all import QQ,PolynomialRing
        R=PolynomialRing(QQ,names=('x','y'));x,y=R.gens();p=x*x+2*x*y-y+1
        self.assertEqual(to_ring(R,from_ring(p)),p)
    def make(self,**kw):
        args=dict(facets=F,dimension=5,n_factors=2,max_deg=3,small_determinants='true',language='sage',gurobi_interface='skip',file_name='test')
        args.update(kw);return NonRealizabilityTest(**args)
    def test_actual_core_respects_explicit_flag(self):
        f=sample_rank_certified_facet_flags(F,5,1,random_seed=41,candidate_id='a')[0]
        t=self.make(flag='{'+','.join(map(str,f))+'}')
        self.assertEqual(t.run,1);self.assertEqual(t.flag,list(f));self.assertEqual(t.original_facets,F)
        self.assertNotEqual(t.geometry_metadata['facet_bases'][0],F[0])
    def test_bad_width_is_rejected_not_replaced(self):
        with self.assertRaises(ValueError):self.make(flag='{0,1,2,3,4,5,6}').run
    def test_omitted_bases_rejected(self):
        with self.assertRaises(ValueError):self.make(flag='{2,3,4,5,6,7}').run
    def test_rank_basis_for_every_facet(self):
        bases,witness=g.facet_bases(F)
        self.assertEqual(len(bases),len(F))
        for j,b in enumerate(bases):
            self.assertEqual(len(b),5);self.assertTrue(set(b).issubset(F[j]));self.assertEqual(len(witness[j]),5)
    def test_real_core_solve_and_independent_verification(self):
        t=self.make(gurobi_interface='sage',file_name='actual_solve')
        self.assertEqual(t.run,0)
        self.assertEqual(verify_bundle(t.certificate_bundle,F)['status'],'verified_exact')
        self.bundle=t.certificate_bundle
        for change in ('weight','poly','sign','incidence'):
            b=copy.deepcopy(self.bundle)
            if change=='weight':b['terms'][0]['weight']='-1'
            elif change=='poly':
                poly=list(b['generators'][0]['polynomial']);m,c=poly[0];poly[0]=(m,c+5);b['generators'][0]['polynomial']=poly
            elif change=='sign':
                j=next(iter(b['metadata']['column_signs']));b['metadata']['column_signs'][j]*=-1
            else:b['metadata']['facets'][0]=b['metadata']['facets'][0][:-1]
            with self.subTest(change=change):
                with self.assertRaises(ValueError):verify_bundle(b,F)
    def test_variable_and_constant_are_early_generators(self):
        t=self.make();t.run
        polys={p for p,pr in t._stage_generators}
        self.assertIn(((0,1),),polys)
        for i in range(t.R.ngens()):self.assertIn(((1<<(8*i),1),),polys)
        self.assertTrue(all(g.degree(p)<=3 for p,pr in t._all_generators))
    def test_numeric_zero_is_not_a_certificate(self):
        t=self.make();t.run
        with self.assertRaises(ArithmeticError):t.accept_exact_solution([0]*len(t._stage_products))
    def test_saturation_preserves_sign(self):
        p=((1,-2),(257,4))
        q,mon,content=g.saturate(p,2)
        self.assertEqual(mon,1);self.assertEqual(content,2);self.assertEqual(q,((0,-1),(256,2)))
if __name__=='__main__':unittest.main(verbosity=2)
