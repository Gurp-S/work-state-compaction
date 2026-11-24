"""Ignoring unused proposal enumeration leaves the requested alias view unchanged."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from wsc.csm import CSM
from test_csm_source_inspection import MemoryStore


class AliasProjectionTests(unittest.TestCase):
    def test_names_and_canonical_unchanged_while_proposals_are_optional(self):
        store=MemoryStore();self.addCleanup(store.db.close);core=CSM(store)
        with patch('wsc.csm.cem.aliases.proposals',return_value=[{'test':'proposal'}]) as propose:
            old=core.aliases();lean=core.aliases(include_proposals=False)
        self.assertEqual(1,propose.call_count)
        self.assertEqual({k:v for k,v in old.items() if k!='proposals'},
                         {k:v for k,v in lean.items() if k!='proposals'})
        self.assertEqual([],lean['proposals'])
