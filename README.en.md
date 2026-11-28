# SJTU-TPMSHX-TM1

[中文](README.md) · English

TM1 calculates flow, heat transfer and pressure drop in TPMS heat exchangers. It supports full 2D and 3D cases, Quick Design and Bayesian optimization. C++ performs the calculations. Python provides the GUI, CLI and application interfaces.

## Where to find the computation code

```mermaid
flowchart LR
    prep["Prepare · native/preprocess/"]
    subgraph sol["Solve · native/solver/"]
        d2["Full 2D · full_2d.cpp"]
        d3["Full 3D · full_3d.cpp"]
        q["Quick Design · quick_design_driver.cpp"]
    end
    result["Evaluate · native/postprocess/"]
    prep --> d2 --> result
    prep --> d3 --> result
    prep --> q --> result
```

Start with the [2D air example](examples/cpp/air_2d.cpp#L32-L34) to see the three calls in order. Python applications can run a full case with [compute](python/compute.py#L15).

| Stage | C++ source | Python entry |
| --- | --- | --- |
| Prepare the case | [2D case preparation](native/preprocess/preparation_case.cpp#L1021) · [Geometry](native/geometry/) | [prepare_case](python/preprocess/api.py) |
| Solve | [Full 2D](native/solver/full_2d.cpp#L1095) · [Full 3D](native/solver/full_3d.cpp#L1505) · [Quick Design](native/solver/quick_design_driver.cpp#L116) | [run_case](python/solvers/api.py) |
| Evaluate the results | [Metric evaluation](native/postprocess/result_stage.cpp#L1164) | [evaluate](python/postprocess/api.py) |

For fluid properties and common numerical methods, open [native/numerics/](native/numerics/). For flow and thermal models, field results or checkpoints, use the [solver guide](native/solver/README.en.md).

<a id="first-run"></a><a id="从这里开始"></a><a id="start-here"></a>

## Run TM1

Full computation and the GUI support macOS arm64 (Python 3.13) and Windows x64 (Python 3.12 or 3.13). Linux x86_64 supports independent result evaluation.

| Task | Start here |
| --- | --- |
| Run a first case<a id="first-run-on-macos--windows"></a><a id="首次运行macos--windows"></a><a id="run-small-examples"></a><a id="跑通小算例"></a><a id="c-candidate-library-in-the-macos-project-folder"></a><a id="macos-项目文件夹中的-c-候选库"></a> | [Install and build from source](docs/first-run.en.md) · [2D and 3D CLI examples](docs/first-run.en.md#examples) |
| <a id="gui-use"></a>Use the GUI<a id="common-gui-workflow"></a><a id="gui-常用流程"></a> | [Load a case, run it and view results](docs/gui-guide.en.md) · [Quick Design](docs/gui-guide.en.md#quick-design) · [Optimization](docs/gui-guide.en.md#optimization) |
| Call TM1 from another program<a id="three-modules"></a><a id="三个模块"></a> | [Python and CLI stage calls](docs/first-run.en.md#stage-api) · [C++ SDK](docs/native-stages.md) · [Data contracts](docs/contracts/three_module_v1/README.md) |
| <a id="环境与检查"></a>Develop or verify a change<a id="environment-and-checks"></a><a id="collaboration-and-merge"></a><a id="协作与合并"></a> | [Contributor extension guide](docs/extending.md) ([fluid or Nu](docs/extending.md#new-fluid-or-nu-closure), [GUI panel](docs/extending.md#new-gui-panel-or-dialog), [topology](docs/extending.md#third-tpms-topology)) · [Local checks and CI](docs/verification.en.md) · [Collaboration](docs/collaboration.md) |
| Check physical scope or evidence<a id="connected-capabilities-and-boundaries"></a><a id="已接线能力与边界"></a><a id="data-and-historical-evidence"></a><a id="数据与历史证据"></a> | [Capabilities and limits](docs/capabilities.en.md) · [Model sources](docs/model-resources.en.md) · [Historical results](docs/history/README.en.md) |

[Repository and documentation map](docs/README.en.md) · [Python source map](python/README.en.md) · [Desktop deployment](docs/desktop.en.md)
