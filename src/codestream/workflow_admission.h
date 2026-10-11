// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Yunho Cho

#pragma once

#include <cstdint>
#include <optional>
#include <utility>

#include "codestream/workflow_admission_scope.h"
#include "codestream/workflow_storage_plan.h"
#include "core/execution_domain.h"
#include "gpu/backend.h"
#include "gpu/metal/metal_backend.h"

namespace gjxl::codestream_internal {

/// Normal option/geometry validation followed by existing backend qualification
/// and complete planning. No managed backing is allocated. Automatic exact
/// searches may initialize Metal earlier, but never change candidate selection.
/// When non-null, backend_selection_nanoseconds accumulates the selection call
/// within this plan, including production backend initialization. No clocks are
/// read for a null accumulator. Failure leaves the accumulator unchanged.
[[nodiscard]] Status PlanWorkflowAdmission(Extent2D source, const WorkflowStorageOptions &options,
                                           GpuBackend *supplied_backend,
                                           bool supplied_backend_is_qualified,
                                           bool resolve_production_backend,
                                           WorkflowStoragePlan *out,
                                           uint64_t *backend_selection_nanoseconds = nullptr);

} // namespace gjxl::codestream_internal
