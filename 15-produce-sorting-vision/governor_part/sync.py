
'''
Sync with camera and machine's sensor's part.
method 1 :
    need to match each sensor's timestamp with camera's timestamp.
    sensor's timestamp will be send to camera (center of camera), 
    when cup's position is detected by camera,
    and we will send to them when we are finished screening potato's condition.
    than, we will send to them right that cup's potato's condition is screened.
    and then, cup will be moved to next action.

method 2:
    just we promised each other, they just send to us when they sensing the potato was arrived,
    and we just count time from that moment, and we will send to them when we are finished screening potato's condition.
    and then, we will send to them what time's the cup's potato's condition is screened.
    and then, cup will be moved to next action when they count the time from the moment they received the signal from us.
'''

def timer():
    pass