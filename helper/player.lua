-- Countdown and input live in the same window as all media. No Tk/X11 overlay.
local mp = require 'mp'
local utils = require 'mp.utils'
local state = {rotation = 0, footer_left = '', footer_right = '', status = ''}
local overlay = mp.create_osd_overlay('ass-events')
local previous = ''

local function escape(text)
    return tostring(text or ''):gsub('\\', '\\' .. '\239\187\191'):gsub('{', '\\{'):gsub('}', '\\}'):gsub('\n', '\\N')
end

local function render()
    local deadline = tonumber(state.deadline)
    local left = deadline and math.max(0, math.ceil(deadline - os.time())) or nil
    local countdown = left and tostring(left) or ''
    if countdown ~= state.last_countdown then
        mp.commandv('script-message', 'eposter-state', 'countdown', countdown)
        state.last_countdown = countdown
    end
    local w, h = mp.get_osd_size()
    if not w or w <= 0 or h <= 0 then return end
    local rotation = tonumber(state.rotation) or 0
    local lw, lh = w, h
    if rotation == 90 or rotation == 270 then lw, lh = h, w end
    -- Keep in sync with overlay_scale/uncover_overlays in display_handler.py.
    local scale = math.max(0.75, math.min(w, h) / 1080)
    local lines = {}
    local function position(x, y)
        if rotation == 90 then return w-y, x end
        if rotation == 180 then return w-x, h-y end
        if rotation == 270 then return y, h-x end
        return x, y
    end
    local function tags(x, y, alignment)
        local px, py = position(x, y)
        return string.format('\\rDefault\\fscx100\\fscy100\\an%d\\pos(%.2f,%.2f)\\frz%d\\bord0\\shad0', alignment or 7, px, py, -rotation)
    end
    local function text(x, y, value, size, color, alignment, bold, font)
        lines[#lines+1] = '{' .. tags(x,y,alignment) .. '\\fn' .. (font or 'DejaVu Sans Mono') .. '\\b' .. (bold and '1' or '0') .. '\\fs' .. size .. '\\1c&H' .. color .. '&}' .. escape(value)
    end
    local function box(x, y, width, height, color, alpha, radius)
        local r = radius or 0
        local path = string.format('m %d 0 l %d 0 b %d 0 %d 0 %d %d l %d %d b %d %d %d %d %d %d l %d %d b 0 %d 0 %d 0 %d l 0 %d b 0 0 0 0 %d 0',
            r,width-r,width,width,width,r,width,height-r,width,height,width,height,width-r,height,r,height,height,height,height-r,r,r)
        lines[#lines+1] = '{' .. tags(x,y) .. '\\1c&H' .. color .. '&\\1a&H' .. alpha .. '&\\p1}' .. path .. '{\\p0}'
    end
    -- The renderer reserves this strip outside the media viewport.
    local footer_height = math.floor(72*scale + 0.5)
    local center_y = lh-footer_height/2
    box(0,lh-footer_height,lw,footer_height,'F5F5F5','00',0)
    box(0,lh-footer_height,lw,math.max(1,math.floor(scale)),'E0DDDA','00',0)
    local value = deadline and string.format('%02d:%02d', math.floor(left/60), left%60) or ''
    local urgent = left and left <= 60
    local warning = left and left <= 120
    local timer_size = math.floor((urgent and 50 or 44)*scale)
    -- Reserve room for the larger final-minute digits without shifting labels.
    local timer_width = math.min(lw*0.32, math.max(176*scale, math.max(5,#value)*50*scale*0.65+32*scale))
    if deadline then
        timer_size = math.min(timer_size, math.floor((timer_width-24*scale)/(#value*0.65)))
        -- ASS colors are BGR: white, yellow at 2:00, red at 1:00.
        local background = urgent and '1C1CB9' or (warning and '8AF0FE' or 'FFFFFF')
        local foreground = '000000'
        -- A fine outline gives the white timer a clear, restrained edge.
        box((lw-timer_width)/2-scale,lh-footer_height+5*scale,timer_width+2*scale,footer_height-10*scale,
            'DEDAD6','00',math.floor(17*scale))
        box((lw-timer_width)/2,lh-footer_height+6*scale,timer_width,footer_height-12*scale,
            background,'00',math.floor(16*scale))
        text(lw/2,center_y,value,timer_size,foreground,5,true)
    end
    -- One continuous Paper ID label, balanced against the secondary address.
    -- Equal outer padding and a reserved center keep the footer aligned.
    local padding = 24*scale
    local side_width = (lw-timer_width)/2-padding-20*scale
    local paper = state.footer_left or ''
    local address = state.footer_right or ''
    local paper_size = math.max(1, math.min(math.floor(32*scale),
        math.floor(side_width/(math.max(1,#paper)*0.7))))
    local address_size = math.max(1, math.min(math.floor(24*scale),
        math.floor(side_width/(math.max(1,#address)*0.65))))
    text(padding,center_y,paper,paper_size,'242424',4,true,'DejaVu Sans')
    text(lw-padding,center_y,address,address_size,'635950',6)
    if state.status and state.status ~= '' then
        local size = math.max(18, math.floor(lw/45))
        local value = tostring(state.status)
        local x = math.max(24, (lw - #value*size*0.6)/2)
        box(0,lh/2-12,lw,size*2.2,'000000','30',0)
        text(x,lh/2,value,size,'FFFFFF')
    end
    local data = table.concat(lines, '\n')
    local key = data .. w .. ':' .. h
    if key == previous then return end
    previous = key
    overlay.res_x, overlay.res_y, overlay.data = w, h, data
    overlay:update()
end

mp.register_script_message('eposter-overlay', function(json)
    local parsed = utils.parse_json(json)
    if parsed then state = parsed; previous = ''; render() end
end)
mp.observe_property('osd-dimensions', 'native', function() previous = ''; render() end)
mp.add_periodic_timer(0.1, render)

local function send(key, x, y)
    mp.commandv('script-message', 'eposter-input', key, tostring(x or 0), tostring(y or 0))
end
for _, key in ipairs({'q','ESC','ENTER','SPACE','UP','DOWN','PGUP','PGDWN','WHEEL_UP','WHEEL_DOWN'}) do
    mp.add_forced_key_binding(key, 'eposter-' .. key, function() send(key) end, {repeatable=true})
end
for _, key in ipairs({'m', 'M'}) do
    mp.add_forced_key_binding(key, 'eposter-menu-' .. key, function() send('M') end)
end
local press = nil
mp.add_forced_key_binding('MBTN_LEFT', 'eposter-click', function(event)
    local x, y = mp.get_mouse_pos()
    if event.event == 'down' then
        press = {x=x, y=y}
    elseif event.event == 'up' then
        if press and math.abs(y-press.y) + math.abs(x-press.x) > 15 then
            send('DRAG', x-press.x, y-press.y)
        else
            send('CLICK', x, y)
        end
        press = nil
    elseif event.event == 'press' then
        send('CLICK', x, y)
    end
end, {complex=true})
-- Prevent default double click fullscreen toggles and right click actions.
mp.add_forced_key_binding('MBTN_LEFT_DBL', 'eposter-double', function() end)
mp.add_forced_key_binding('MBTN_RIGHT', 'eposter-right', function() send('ESC') end)

mp.register_script_message('eposter-ping', function()
    mp.commandv('script-message', 'eposter-state', 'ready', '1')
end)
