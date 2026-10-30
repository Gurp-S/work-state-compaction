"""Uncompressed/no-history controls sharing the current actor and runtime."""
from .paired_cell import Cell,save,import_fresh,accept_t1,load_candidate
from .baseline_material import import_baseline


class BaselineCell(Cell):
    def run(self):
        ticket,phase=None,None
        result=None
        try:
            ticket=self.start('continuation')
            session,bootstrap=self.open('native')
            prefix=self.inputs['prefix'] if self.name=='A' else []
            import_baseline(session,prefix,bootstrap,self.folder/'native-session')
            phase=self.call(ticket,session,self.inputs['request'],'continuation')
            for item in self.sessions:self.close_session(item)
            self.settle(ticket,phase);ticket=None
            result=self.evaluate_artifact()
            result['task_success']=result['success']
            budget=self.ledger.snapshot()['budget']
            complete=bool(phase.get('completed') and not phase.get('failure') and phase.get('usage_complete')
                and not budget['arms'][self.run_id]['stopped'] and not budget['study']['uncertain'])
            result['execution_complete']=complete
            result['success']=result['run_success']=bool(result['task_success'] and complete)
        except BaseException as error:
            if ticket is not None:self.settle(ticket,phase,error)
            result=dict(success=False,run_success=False,task_success=None,execution_complete=False,
                error_type=type(error).__name__,error=str(error))
        finally:
            cleanup=[self.close_session(session) for session in self.sessions]
            if result is not None:
                self.ledger.finish(self.run_id,result)
                save(self.folder/'result.json',dict(**result,cleanup=cleanup))
        return result
