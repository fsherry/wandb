package server

import (
	"github.com/wandb/wandb/nexus/pkg/fsm"
	"github.com/wandb/wandb/nexus/pkg/service"
)

type FlowControlContext struct {
	forwardedOffset int64
	sentOffset int64
	writtenOffset int64
}

type FlowControl struct {
	sendRecord   func(record *service.Record)
	sendPause    func()
	stateMachine *fsm.Fsm[*service.Record, *FlowControlContext]
}

type StateForwarding struct {
	fsm.FsmState[*service.Record, *FlowControlContext]

	sendRecord func(record *service.Record)
}

func (s *StateForwarding) OnCheck(record *service.Record) {
	s.sendRecord(record)
}

func (s *StateForwarding) OnEnter(record *service.Record, context *FlowControlContext) {
}

func (s *StateForwarding) OnExit(record *service.Record) *FlowControlContext {
	return nil
}

func (s *StateForwarding) shouldPause(record *service.Record) bool {
	return false
}

func (s *StateForwarding) doPause(record *service.Record) {
}

type StatePausing struct {
	fsm.FsmState[*service.Record, *FlowControlContext]
}

func (s *StatePausing) OnCheck(record *service.Record) {
}

func (s *StatePausing) OnEnter(record *service.Record, context *FlowControlContext) {
}

func (s *StatePausing) OnExit(record *service.Record) *FlowControlContext {
	return nil
}

func (s *StatePausing) shouldUnpause(record *service.Record) bool {
	return false
}

func (s *StatePausing) doUnpause(record *service.Record) {
}

func (s *StatePausing) shouldRecover(record *service.Record) bool {
	return false
}

func (s *StatePausing) doRecover(record *service.Record) {
}

func (s *StatePausing) shouldQuiesce(record *service.Record) bool {
	return false
}

func (s *StatePausing) doQuiesce(record *service.Record) {
}

func NewFlowControl(sendRecord func(record *service.Record), sendPause func()) *FlowControl {
	flowControl := &FlowControl{
		sendRecord: sendRecord,
		sendPause:  sendPause,
	}

	stateMachine := fsm.NewFsm[*service.Record, *FlowControlContext]()
	forwarding := &StateForwarding{
		sendRecord: sendRecord,
	}
	pausing := &StatePausing{}
	stateMachine.AddState(forwarding)
	stateMachine.AddState(pausing)

	forwarding.AddTransition(forwarding.shouldPause, pausing, forwarding.doPause)
	pausing.AddTransition(pausing.shouldUnpause, forwarding, pausing.doUnpause)
	pausing.AddTransition(pausing.shouldRecover, forwarding, pausing.doRecover)
	pausing.AddTransition(pausing.shouldQuiesce, forwarding, pausing.doQuiesce)

	flowControl.stateMachine = stateMachine
	return flowControl
}

func (f *FlowControl) Flow(record *service.Record) {
	f.stateMachine.Input(record)
}
