#!/usr/bin/env python3
"""Complete synthetic comparison, including a rebuild from an offline archive."""
import copy
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from claimledger import core as c, manuscript as m, archive as a, comparison as d


def example(root):
    root=Path(root)
    root.mkdir()  # Never reuse an existing destination.
    before=c.new()
    c.import_source(before,'notice_v1','Sample notice\r\nThe room opens at 09:00.\r\n','Invented notice, revision 1')
    c.append(before,'claims',{'id':'opening','text':'The sample notice says the room opens at 09:00.'})
    c.append(before,'claims',{'id':'hypothesis','text':'Visitors may prefer an earlier opening. This is an uncited hypothesis.'})
    c.cite(before,'opening_v1','opening','notice_v1','The room opens at 09:00.')
    first={'version':1,'title':'Before: an invented notice','sections':[
        {'heading':'Notice','claims':[{'id':'opening','citations':['opening_v1']}]},
        {'heading':'Discussion','claims':[{'id':'hypothesis','citations':[]},{'id':'opening','citations':[]}]}]}
    after=copy.deepcopy(before)
    c.import_source(after,'notice_v2','Sample revised notice\nThe room opens at 10:00.\n','Invented notice, revision 2')
    # A separately saved authored revision retains the author's asserted claim identity.
    after['claims'][0]['text']='The revised sample notice says the room opens at 10:00.'
    c.cite(after,'opening_v2','opening','notice_v2','The room opens at 10:00.')
    c.append(after,'claims',{'id':'new_note','text':'Check the sample notice before visiting; this is an uncited suggestion.'})
    second={'version':1,'title':'After: an invented notice','sections':[
        {'heading':'Discussion','claims':[{'id':'opening','citations':[]},{'id':'new_note','citations':[]}]},
        {'heading':'Notice','claims':[{'id':'opening','citations':['opening_v2']}]}]}
    for label,data,spec in [('before',before,first),('after',after,second)]:
        c.save(root/(label+'.json'),data)
        (root/(label+'-spec.json')).write_bytes(c.encoded(spec))
        m.export(root/(label+'.json'),root/(label+'-spec.json'),root/label)
    a.export(root/'after.json',root/'after.zip')
    a.restore(root/'after.zip',root/'restored')
    m.export(root/'restored/ledger.json',root/'after-spec.json',root/'rebuilt-after')
    d.export(root/'before',root/'after',root/'comparison')
    d.export(root/'before',root/'rebuilt-after',root/'restored-comparison')
    for name in ('comparison.json','comparison.html'):
        assert (root/'comparison'/name).read_bytes()==(root/'restored-comparison'/name).read_bytes()
    return root/'comparison/comparison.html'


if __name__=='__main__':
    if len(sys.argv)!=2: raise SystemExit('usage: python3 scripts/comparison_example.py FRESH_DIRECTORY')
    print(example(sys.argv[1]))
