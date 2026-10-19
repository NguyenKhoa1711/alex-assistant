package vn.alex.phone;

public final class AlertPolicyTests {
    static int checks;
    static void check(boolean value, String message) {
        checks++;
        if (!value) throw new AssertionError(message);
    }
    public static void main(String[] args) {
        run();
        System.out.println("PASS " + checks + " policy/hold checks; no messages dispatched");
    }
    static void run() {
        AlertPlan low = new AlertPlan(1), mid = new AlertPlan(2), high = new AlertPlan(3);
        check(low.recipients.length == 1 && low.recipients[0] == 0 && !low.sms && low.message.isEmpty(), "level1 scope");
        check(mid.recipients.length == 1 && !mid.sms && mid.message.equals(AlertPlan.CALL), "level2 call request");
        check(high.recipients.length == 2 && high.recipients[0] == 0 && high.recipients[1] == 1 && high.sms, "level3 both channels and contacts");
        check(high.message.equals("con đang gặp nguy hiểm, xem vị trí con gửi r tới giúp con nha, con ko gọi hay nghe máy được nên đừng gọi."), "exact SOS");
        check(AlertPlan.phone("+84 900-000-001").equals("+84900000001"), "phone formatting");
        check(AlertPlan.phone("112").isEmpty(), "no emergency short-code accident");
        check(AlertPlan.phone("0900000001;0900000002").isEmpty(), "no compound recipient");
        check(AlertPlan.phone("0900000001 ext2").isEmpty(), "no ambiguous number");
        check(AlertPlan.canonicalPhone("0900000001").equals(AlertPlan.canonicalPhone("+84900000001")), "duplicate VN number");
        check(!AlertPlan.contactKey("Đại ca").equals(AlertPlan.contactKey("Dai ca")), "no fuzzy recipient substitution");
        check(AlertPlan.contactKey("Đại ca\n\n").equals(AlertPlan.contactKey("Đại ca")), "Zalo virtual contact row");
        check(!AlertPlan.contactKey("học tập\nThành viên: Đại ca\n").equals(AlertPlan.contactKey("Đại ca")), "group member is not recipient");
        for (int bad : new int[]{-1, 0, 4}) {
            boolean rejected = false;
            try { new AlertPlan(bad); } catch (IllegalArgumentException e) { rejected = true; }
            check(rejected, "invalid level");
        }
        HoldGate hold = new HoldGate();
        hold.down(100);
        check(!hold.fire(3099), "must wait full 3s");
        check(hold.fire(3100), "fires at deadline");
        check(!hold.fire(6100), "continued hold must not repeat");
        hold.down(7000); hold.cancel();
        check(!hold.fire(11000), "release/focus loss cancels");
        hold.down(12000); check(!hold.fire(12500), "new hold starts anew");
        hold.cancel(); hold.down(14000);
        check(!hold.fire(15500), "short presses cannot accumulate");
        check(hold.fire(17000), "subsequent deliberate hold works");
        QuietPolicyTests.run();
    }
}
