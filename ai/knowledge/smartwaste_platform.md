# SmartWaste Platform Guide

How citizens and administrators use the SmartWaste application: reporting,
tracking, statuses, notifications and this assistant.

## Reporting waste on SmartWaste

Citizens open **Report Waste**, allow or enter the location, choose one of
the platform waste categories (Open Garbage, Plastic Waste, Food Waste,
Construction Debris, E-Waste, Medical Waste, Drain & Sewer Waste, Street
Sweeping), set a priority (Low, Medium, High, Emergency), describe the
problem in at least 15 characters and optionally attach a photo.

On submission the platform stores the complaint, runs its classification
and urgency models, checks for possible duplicates near the location and
returns a tracking ID such as SW-00042. Every complaint gets a status
timeline and a PDF receipt.

Keywords: report waste kaise kare, शिकायत कैसे दर्ज करें, new complaint
form, complaint kaise kare SmartWaste par.

## Tracking a complaint

Use **Track** with the tracking ID (for example SW-00042) or the
complaint number. A mobile number alone never returns results - it is only
accepted together with the ID as confirmation. Signed-in citizens also see
their full history under **My Complaints**, with status filters and the
latest administrator remarks.

Notifications appear in the Notifications bell whenever the status changes.

Keywords: complaint status kaise check kare, शिकायत की स्थिति, track my
complaint, tracking ID.

## Complaint status lifecycle

The legal statuses are: Submitted, Under Review, Assigned, In Progress,
Resolved and Rejected. A typical happy path is Submitted -> Under Review ->
Assigned -> In Progress -> Resolved.

Rejected complaints can be appealed back to Under Review, and Resolved
complaints can be reopened to In Progress. Status changes are recorded in
the complaint history with the administrator's remark, so citizens always
see why a status changed.

Keywords: complaint status kya hota hai, status meaning, submitted under
review assigned in progress resolved.

## Feedback on resolved complaints

After a complaint is Resolved, the owner can rate it 1-5 with a comment.
Feedback feeds the municipal performance view and is shown on the
complaint page.

Keywords: complaint feedback, rating dena, resolved complaint rate.

## What SmartWaste AI can do

SmartWaste AI is the assistant built into SmartWaste. Citizens can ask it
to explain waste segregation, recycling and composting, register a
complaint step by step, and track their own complaints. Administrators get
a separate assistant that explains complaint statistics, hotspots,
forecasts and recommendations from the live database.

The assistant replies in English, Hindi or Hinglish and remembers the
conversation. It cannot change complaint statuses or see data the signed-in
user is not allowed to see - those actions stay in the hands of people in
the proper console.

Keywords: SmartWaste AI assistant, chatbot kya kar sakta hai, AI se baat,
हिन्दी में सहायता.

## Accounts, privacy and roles

Citizens sign up with email and password; administrators sign in with the
configured console credentials. Complaints belong to the account that
created them - other citizens cannot open them, and only administrators
see the full queue.

Contact details, mobile numbers and internal identifiers are masked in
shared views. Chat history is stored per account and can be cleared from
the chat window at any time.

Keywords: account privacy, login signup, data kahan store hota hai,
chat history delete.
