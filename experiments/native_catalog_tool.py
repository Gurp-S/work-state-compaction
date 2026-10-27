"""Optional bounded metadata operation on the existing source-tool channel."""
from copy import deepcopy
from time import monotonic
from native_source_tool import SOURCE_TOOL
from native_source_tool_budget import BudgetResultSourceToolHandler
from native_deferred_catalog import decoded_catalog,reply
from wsc.snapshot_literal_access import SnapshotLiteralAccess
from wsc.source_access import serialized
from wsc.evidence import authorize
from wsc.contracts import require,encode,digest

CATALOG_TOOL=deepcopy(SOURCE_TOOL)
CATALOG_TOOL['inputSchema']['properties']['operation']['enum'].append('catalog')
CATALOG_TOOL['description']+=' catalog returns bound sealed-snapshot event metadata and source budget facts; current read permissions are checked. Catalog data does not certify current storage health.'


class CatalogAccess(SnapshotLiteralAccess):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.catalog_payload=None;self.catalog_binding=None;self.catalog_calls=0
    def describe(self):
        return {**super().describe(),'operations':['read','find','catalog'],
            'catalog_scope':'Sealed metadata with current read permission checks, no current storage validation.',
            'catalog_budget':'Shared call limit and result byte limit; snapshot metadata scans use the search source/deadline limits. No live source row is read by catalog.'}
    def install_catalog(self,payload,binding):
        if payload is None:self.catalog_payload=None;self.catalog_binding=None;return
        _,aliases=decoded_catalog(payload,binding)
        require(encode(payload['snapshot'])==encode(self.snapshot_binding) and aliases==self.order,'catalog_snapshot_binding_changed')
        require(len(aliases)<=self.search_limits.max_scan_sources_per_call,'catalog_source_budget_exhausted')
        require(len(encode(reply(payload,calls=self.limits.max_calls,catalog_calls=self.limits.max_calls)).encode())<=self.limits.max_return_bytes,'catalog_return_budget_exhausted')
        self.catalog_payload=deepcopy(payload);self.catalog_binding=deepcopy(binding)
    @serialized
    def catalog_read(self):
        self._begin();self.catalog_calls+=1
        require(self.catalog_payload is not None,'source_catalog_unavailable')
        payload=self.catalog_payload;_,aliases=decoded_catalog(payload,self.catalog_binding)
        require(encode(payload['snapshot'])==encode(self.snapshot_binding),'catalog_snapshot_binding_changed')
        deadline=monotonic()+self.search_limits.max_scan_milliseconds_per_call/1000
        def permissions():
            for alias in aliases:
                require(monotonic()<deadline,'catalog_scan_deadline_exhausted')
                authorize(self.store,self.access,self.bound[alias])
        permissions();value=reply(payload,calls=self.calls,catalog_calls=self.catalog_calls);permissions()
        require(len(encode(value).encode())<=self.limits.max_return_bytes,'catalog_return_budget_exhausted')
        return value


class CatalogToolHandler(BudgetResultSourceToolHandler):
    def install_catalog(self,payload,binding):self.reader.install_catalog(payload,binding)
    def project_material(self,material):
        from native_deferred_catalog import project
        result,payload,binding=project(material,max_return_bytes=self.reader.limits.max_return_bytes,
            max_calls=self.reader.limits.max_calls,max_sources=self.reader.search_limits.max_scan_sources_per_call)
        self.install_catalog(payload,binding)
        return result,payload,binding
    def execute_arguments(self,args):
        if isinstance(args,dict) and args.get('operation')=='catalog':
            require(set(args)=={'operation'},'source_tool_arguments_invalid')
            return self.reader.catalog_read()
        return super().execute_arguments(args)
