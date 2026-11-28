#include "opendeck/windows_volume.hpp"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;

void bind_windows_volume(py::module_ &module) {
    using namespace opendeck::windows;
    module.def("_read_output_volume", &read_output_volume,
               py::call_guard<py::gil_scoped_release>());
    module.def("_read_output_mute", &read_output_mute, py::call_guard<py::gil_scoped_release>());
    module.def("_set_output_volume", &set_output_volume, py::call_guard<py::gil_scoped_release>());
    module.def("_set_output_mute", &set_output_mute, py::call_guard<py::gil_scoped_release>());
    py::class_<VolumeWatch>(module, "_WindowsVolumeWatch")
        .def(py::init<>())
        .def("start", &VolumeWatch::start, py::call_guard<py::gil_scoped_release>())
        .def("wait", &VolumeWatch::wait, py::call_guard<py::gil_scoped_release>())
        .def("refresh", &VolumeWatch::refresh, py::call_guard<py::gil_scoped_release>())
        .def("cancel", &VolumeWatch::cancel, py::call_guard<py::gil_scoped_release>())
        .def("close", &VolumeWatch::close, py::call_guard<py::gil_scoped_release>());
}
