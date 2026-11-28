#include "opendeck/windows_volume.hpp"

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <audioclient.h>
#include <endpointvolume.h>
#include <mmdeviceapi.h>
#include <windows.h>

#include <atomic>
#include <cmath>
#include <memory>

namespace opendeck::windows {
namespace {

std::uint32_t status(HRESULT result) {
    return SUCCEEDED(result) ? 0 : static_cast<std::uint32_t>(result);
}

template <class T> class ComPointer {
public:
    ComPointer() = default;
    ComPointer(const ComPointer &) = delete;
    ComPointer &operator=(const ComPointer &) = delete;
    ~ComPointer() { reset(); }
    T *operator->() const { return value; }
    T *get() const { return value; }
    T **put() {
        reset();
        return &value;
    }
    void reset() {
        if (value) {
            value->Release();
            value = nullptr;
        }
    }

private:
    T *value = nullptr;
};

class Apartment {
public:
    HRESULT open() {
        if (initialized)
            return S_OK;
        const auto result = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
        initialized = SUCCEEDED(result);
        return result;
    }
    HRESULT pin_mta() { return CoIncrementMTAUsage(&usage); }
    void close() {
        if (initialized) {
            CoUninitialize();
            initialized = false;
        }
        if (usage) {
            CoDecrementMTAUsage(usage);
            usage = nullptr;
        }
    }
    ~Apartment() { close(); }

private:
    bool initialized = false;
    CO_MTA_USAGE_COOKIE usage = nullptr;
};

HRESULT create_enumerator(ComPointer<IMMDeviceEnumerator> &enumerator) {
    return CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL,
                            __uuidof(IMMDeviceEnumerator),
                            reinterpret_cast<void **>(enumerator.put()));
}

HRESULT default_volume(IMMDeviceEnumerator *enumerator, ComPointer<IAudioEndpointVolume> &volume) {
    ComPointer<IMMDevice> device;
    auto result = enumerator->GetDefaultAudioEndpoint(eRender, eConsole, device.put());
    if (FAILED(result))
        return result;
    return device->Activate(__uuidof(IAudioEndpointVolume), CLSCTX_ALL, nullptr,
                            reinterpret_cast<void **>(volume.put()));
}

template <class Operation> HRESULT with_volume(Operation operation) {
    Apartment apartment;
    APTTYPE kind;
    APTTYPEQUALIFIER qualifier;
    auto result = CoGetApartmentType(&kind, &qualifier);
    if (result == CO_E_NOTINITIALIZED)
        result = apartment.open();
    else if (SUCCEEDED(result) && (qualifier == APTTYPEQUALIFIER_IMPLICIT_MTA ||
                                   qualifier == APTTYPEQUALIFIER_NA_ON_IMPLICIT_MTA))
        result = apartment.pin_mta();
    if (FAILED(result))
        return result;
    ComPointer<IMMDeviceEnumerator> enumerator;
    result = create_enumerator(enumerator);
    if (FAILED(result))
        return result;
    ComPointer<IAudioEndpointVolume> volume;
    result = default_volume(enumerator.get(), volume);
    return FAILED(result) ? result : operation(volume.get());
}

struct Signals {
    Signals() {
        changed = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        if (!changed) {
            error = HRESULT_FROM_WIN32(GetLastError());
            return;
        }
        canceled = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        if (!canceled)
            error = HRESULT_FROM_WIN32(GetLastError());
    }
    ~Signals() {
        if (changed)
            CloseHandle(changed);
        if (canceled)
            CloseHandle(canceled);
    }
    void notify() const {
        if (!stopping.load())
            SetEvent(changed);
    }
    void cancel() {
        stopping.store(true);
        if (canceled)
            SetEvent(canceled);
    }
    HANDLE changed = nullptr;
    HANDLE canceled = nullptr;
    HRESULT error = S_OK;
    std::atomic<bool> stopping{false};
};

// OS callbacks only signal an event. Rebinding and COM release run on the owner.
class Notifications final : public IMMNotificationClient, public IAudioEndpointVolumeCallback {
public:
    explicit Notifications(std::shared_ptr<Signals> signals) : signals(std::move(signals)) {}

    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID id, void **object) override {
        if (!object)
            return E_POINTER;
        *object = nullptr;
        if (IsEqualIID(id, __uuidof(IUnknown)) || IsEqualIID(id, __uuidof(IMMNotificationClient)))
            *object = static_cast<IMMNotificationClient *>(this);
        else if (IsEqualIID(id, __uuidof(IAudioEndpointVolumeCallback)))
            *object = static_cast<IAudioEndpointVolumeCallback *>(this);
        else
            return E_NOINTERFACE;
        AddRef();
        return S_OK;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return ++references; }
    ULONG STDMETHODCALLTYPE Release() override {
        const auto remaining = --references;
        if (!remaining)
            delete this;
        return remaining;
    }
    HRESULT STDMETHODCALLTYPE OnNotify(PAUDIO_VOLUME_NOTIFICATION_DATA) override {
        signals->notify();
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE OnDefaultDeviceChanged(EDataFlow flow, ERole role, LPCWSTR) override {
        if (flow == eRender && role == eConsole)
            signals->notify();
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE OnDeviceStateChanged(LPCWSTR, DWORD) override {
        signals->notify();
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE OnDeviceAdded(LPCWSTR) override {
        signals->notify();
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE OnDeviceRemoved(LPCWSTR) override {
        signals->notify();
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE OnPropertyValueChanged(LPCWSTR, const PROPERTYKEY) override {
        signals->notify();
        return S_OK;
    }

private:
    std::atomic<ULONG> references{1};
    std::shared_ptr<Signals> signals;
};

} // namespace

std::pair<std::uint32_t, float> read_output_volume() {
    float level = 0;
    const auto result = with_volume(
        [&](IAudioEndpointVolume *volume) { return volume->GetMasterVolumeLevelScalar(&level); });
    return {status(result), level};
}

std::pair<std::uint32_t, bool> read_output_mute() {
    BOOL muted = FALSE;
    const auto result =
        with_volume([&](IAudioEndpointVolume *volume) { return volume->GetMute(&muted); });
    return {status(result), muted != FALSE};
}

std::uint32_t set_output_volume(float level) {
    if (!std::isfinite(level) || level < 0 || level > 1)
        return status(E_INVALIDARG);
    return status(with_volume([&](IAudioEndpointVolume *volume) {
        return volume->SetMasterVolumeLevelScalar(level, nullptr);
    }));
}

std::uint32_t set_output_mute(bool muted) {
    return status(with_volume([&](IAudioEndpointVolume *volume) {
        return volume->SetMute(muted ? TRUE : FALSE, nullptr);
    }));
}

struct VolumeWatch::State {
    Apartment apartment;
    ComPointer<IMMDeviceEnumerator> enumerator;
    ComPointer<IAudioEndpointVolume> volume;
    ComPointer<Notifications> notifications;
    std::shared_ptr<Signals> signals = std::make_shared<Signals>();
    DWORD owner = 0;
    bool system_registered = false;
    bool volume_registered = false;

    HRESULT on_owner() const { return owner == GetCurrentThreadId() ? S_OK : RPC_E_WRONG_THREAD; }
    HRESULT detach_volume() {
        if (volume_registered) {
            const auto result = volume->UnregisterControlChangeNotify(notifications.get());
            if (FAILED(result))
                return result;
            volume_registered = false;
        }
        volume.reset();
        return S_OK;
    }
    HRESULT refresh() {
        auto result = on_owner();
        if (FAILED(result))
            return result;
        result = detach_volume();
        if (FAILED(result))
            return result;
        result = default_volume(enumerator.get(), volume);
        if (FAILED(result))
            return result;
        result = volume->RegisterControlChangeNotify(notifications.get());
        volume_registered = SUCCEEDED(result);
        return result;
    }
    HRESULT close() {
        signals->cancel();
        if (!owner)
            return S_OK;
        auto result = on_owner();
        if (FAILED(result))
            return result;
        const auto volume_result = detach_volume();
        HRESULT system_result = S_OK;
        if (system_registered) {
            system_result = enumerator->UnregisterEndpointNotificationCallback(notifications.get());
            if (SUCCEEDED(system_result))
                system_registered = false;
        }
        if (FAILED(volume_result))
            return volume_result;
        if (FAILED(system_result))
            return system_result;
        notifications.reset();
        enumerator.reset();
        apartment.close();
        owner = 0;
        return S_OK;
    }
};

VolumeWatch::VolumeWatch() : state(std::make_unique<State>()) {}

VolumeWatch::~VolumeWatch() {
    // Failed deregistration must keep callback state and COM ownership alive.
    if (FAILED(state->close()))
        state.release();
}

std::uint32_t VolumeWatch::start() {
    if (state->owner)
        return status(E_UNEXPECTED);
    if (FAILED(state->signals->error))
        return status(state->signals->error);
    auto result = state->apartment.open();
    if (FAILED(result))
        return status(result);
    state->owner = GetCurrentThreadId();
    result = create_enumerator(state->enumerator);
    if (FAILED(result))
        return status(result);
    *state->notifications.put() = new Notifications(state->signals);
    result = state->enumerator->RegisterEndpointNotificationCallback(state->notifications.get());
    if (FAILED(result))
        return status(result);
    state->system_registered = true;
    result = state->refresh();
    if (result == HRESULT_FROM_WIN32(ERROR_NOT_FOUND) || result == E_NOINTERFACE ||
        result == AUDCLNT_E_DEVICE_INVALIDATED)
        return 0;
    return status(result);
}

std::pair<std::uint32_t, bool> VolumeWatch::wait() {
    const auto result = state->on_owner();
    if (FAILED(result))
        return {status(result), false};
    HANDLE events[] = {state->signals->canceled, state->signals->changed};
    const auto ready = WaitForMultipleObjects(2, events, FALSE, INFINITE);
    if (ready == WAIT_OBJECT_0)
        return {0, false};
    if (ready == WAIT_OBJECT_0 + 1)
        return {0, true};
    return {status(HRESULT_FROM_WIN32(GetLastError())), false};
}

std::uint32_t VolumeWatch::refresh() {
    if (!state->system_registered)
        return status(E_UNEXPECTED);
    return status(state->refresh());
}

void VolumeWatch::cancel() { state->signals->cancel(); }

std::uint32_t VolumeWatch::close() { return status(state->close()); }

} // namespace opendeck::windows
