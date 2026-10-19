package vn.alex.phone;

/** Choose only work not already dispatched; GPS must not block the call-request text. */
final class AlertRoute {
    static final int MESSAGE = 1, LOCATION = 2, DONE = 3;
    static int next(AlertPlan plan, boolean messageHandled, boolean locationHandled, boolean locationOn) {
        if (!plan.message.isEmpty() && !messageHandled) return MESSAGE;
        if (!locationHandled && locationOn) return LOCATION;
        return DONE;
    }
}
