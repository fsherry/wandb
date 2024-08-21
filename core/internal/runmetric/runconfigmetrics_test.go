package runmetric_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/runmetric"
	"github.com/wandb/wandb/core/pkg/service"
)

func TestMetricSelfStep(t *testing.T) {
	rcm := runmetric.NewRunConfigMetrics()

	_ = rcm.ProcessRecord(&service.MetricRecord{
		Name:       "x",
		StepMetric: "y",
	})
	_ = rcm.ProcessRecord(&service.MetricRecord{
		Name:       "y",
		StepMetric: "x",
	})
	config := rcm.ToRunConfigData()

	assert.Len(t, config, 2)

	xidx, yidx := 0, 1
	if config[xidx]["1"] != "x" {
		xidx, yidx = yidx, xidx
	}
	assert.Equal(t, config[xidx]["5"], 1+int64(yidx))
	assert.Equal(t, config[yidx]["5"], 1+int64(xidx))
}