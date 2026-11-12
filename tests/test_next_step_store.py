"""The store steps act from the top of the listing page (B-088): the next-step bar approves for the store and
publishes (or approves and sends an update) itself, instead of sending the owner down the page."""
import unittest

from packages import journey
from tests._helpers import REPO, read

PAGE = "apps/review-dashboard/src/pages/ListingDetail.tsx"


class TopActions(unittest.TestCase):
    def test_every_store_step_gets_its_action_at_the_top(self):
        src = read(REPO / PAGE)
        self.assertIn('const STORE_STEPS = ["approve-for-store", "ready-to-publish", "changed", "ready-to-update", "needs-look"];', src)
        self.assertIn("{STORE_STEPS.includes(st.id) && <StoreStep id={d.item.id} status={st.id} onDone={onStore} />}", src)
        self.assertNotIn(">Review and approve</a>", src, "no button that only scrolls")
        self.assertNotIn(">Go to Publish</a>", src)

    def test_it_acts_on_the_version_shown_like_the_store_panel(self):
        src = read(REPO / PAGE)
        self.assertIn("api.approveStorefront(id, cs.change_set_hash, cs.requested_status)", src)
        self.assertIn("api.publish(id, cs.change_set_hash)", src)
        self.assertIn('See what it sends</a>', src)
        self.assertIn("version={JSON.stringify([d.listing, dr.revision, storeRev])}", src, "the panel below reads again")

    def test_the_words_match(self):
        self.assertIn("here or from the Publish page", journey.status(stage="framed", drafted=True, copy_approved=True,
                                                                     publish_state=None, store_state="approved")["next"])
        for s in ("approve-for-store", "ready-to-publish", "changed", "ready-to-update", "needs-look"):
            self.assertIn(s, journey.LABELS)


class Wizard(unittest.TestCase):
    def test_the_progress_reads_as_numbered_steps(self):
        """B-089: numbered steps on a line, a tick once done (said in words too), the current one marked."""
        src = read(REPO / "apps/review-dashboard/src/components/Status.tsx")
        self.assertIn('<span className="step-dot" aria-hidden="true">{cls === "done" ? "✓" : i + 1}</span>', src)
        self.assertIn('<span className="visually-hidden"> (done)</span>', src)
        self.assertIn('aria-current={i === here && !finished ? "step" : undefined}', src)
        css = read(REPO / "apps/review-dashboard/src/styles.css")
        self.assertIn(".tracker li.done + li::before { background: var(--ok); }", css)


if __name__ == "__main__":
    unittest.main()
