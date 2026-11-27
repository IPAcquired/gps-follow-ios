"""Anchored change to the dashboard's cached-review read path, safe on a staged copy."""
from pathlib import Path
import sys

def candidate(src):
    old='''    profile = read_json(PROFILE, {})
    flight = live_flight_status()
    updates = update_status()
    jev_review = read_json(JEV_FLIGHT_REVIEW, {})'''
    new='''    profile, jev_review = current_log_review(PROFILE, read_json(JEV_FLIGHT_REVIEW, {}))
    flight = live_flight_status()
    updates = update_status()'''
    header='def flight_insights() -> dict:'
    helper='''def current_log_review(path, review):
    """Associate a cached reviewer result with the exact bytes of the active log cohort."""
    try:
        raw = path.read_bytes()
        profile = json.loads(raw)
    except (OSError, ValueError, UnicodeError):
        return {}, {}
    if not isinstance(profile, dict) or profile.get("controller_group") != "APJ-1229/BT-10/BU-2/4.7.3":
        return {}, {}
    if type(profile.get("files")) is not int or profile["files"] <= 0 or not isinstance(review, dict):
        return profile, {}
    digest = hashlib.sha256(raw).hexdigest()
    if (type(review.get("schema")) is not int or review["schema"] != 1 or review.get("mode") != "live_jev_post_flight_review"
            or review.get("source_profile_sha256") != digest or review.get("profile_review_id") != "sha256:" + digest
            or review.get("real_jev_called") is not True or review.get("automatic_change_allowed") is not False
            or review.get("flight_control_authority") is not False or review.get("mavlink_transmit_enabled") is not False
            or review.get("may_write_ardupilot_parameters") is not False):
        return profile, {}
    return profile, review


'''
    before='"No completed flight log yet", "Upload an ArduPilot .BIN after landing for an understandable post-flight summary.", "The analyzed log count is zero."'
    after='"No matching CORVON log yet", "Import a completed ArduCopter 4.7.3 BIN after landing.", "This controller group has no qualified logs. Earlier boards are cataloged separately."'
    gate='if confidence >= 0.80 and sufficient >= 0.70:'
    for pattern in (old,header,before,gate):
        if src.count(pattern)!=1:raise ValueError('Companion baseline differs around the log review.')
    return src.replace(header,helper+header).replace(old,new).replace(before,after).replace(gate,'if jev_review.get("actionable_for_human_review") is True and confidence >= 0.80 and sufficient >= 0.70:')

if __name__=='__main__':
    dest=Path(sys.argv[2])
    if dest.exists():raise FileExistsError('Select an unused candidate path.')
    dest.write_text(candidate(Path(sys.argv[1]).read_text(encoding='utf8')),encoding='utf8',newline='\n')
