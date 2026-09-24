from django.urls import path

from .views import (
    AppointmentCancelView,
    AppointmentCompleteView,
    AppointmentListCreateView,
    AppointmentMaterialsView,
    AppointmentRescheduleView,
    BookingCatalogView,
    BookingScheduleView,
    BookingSlotDaysView,
    BookingSlotsView,
    BookingSlotTimesView,
    BookingStaffView,
    CustomerAnonymizeView,
    PublicBookingCatalogView,
    PublicBookingCreateView,
    PublicBookingDaysView,
    PublicBookingSlotsView,
    PublicBookingTimesView,
    SelfServiceAppointmentView,
    SelfServiceCancelView,
    SelfServiceRescheduleView,
    ServiceMaterialsView,
)

app_name = "booking"

urlpatterns = [
    path("catalog/", BookingCatalogView.as_view(), name="catalog"),
    path("catalog/staff/<uuid:staff_id>/", BookingStaffView.as_view(), name="staff"),
    path("schedule/", BookingScheduleView.as_view(), name="schedule"),
    path("slots/", BookingSlotsView.as_view(), name="slots"),
    path("slots/days/", BookingSlotDaysView.as_view(), name="slot-days"),
    path("slots/times/", BookingSlotTimesView.as_view(), name="slot-times"),
    path("appointments/", AppointmentListCreateView.as_view(), name="appointments"),
    path(
        "appointments/<uuid:appointment_id>/reschedule/",
        AppointmentRescheduleView.as_view(),
        name="reschedule",
    ),
    path(
        "appointments/<uuid:appointment_id>/cancel/", AppointmentCancelView.as_view(), name="cancel"
    ),
    path(
        "appointments/<uuid:appointment_id>/complete/",
        AppointmentCompleteView.as_view(),
        name="complete",
    ),
    path(
        "appointments/<uuid:appointment_id>/materials/",
        AppointmentMaterialsView.as_view(),
        name="appointment-materials",
    ),
    path(
        "catalog/services/<uuid:service_id>/materials/",
        ServiceMaterialsView.as_view(),
        name="service-materials",
    ),
    path(
        "customers/<uuid:customer_id>/anonymize/",
        CustomerAnonymizeView.as_view(),
        name="customer-anonymize",
    ),
    path("public/<slug:public_slug>/", PublicBookingCatalogView.as_view(), name="public-catalog"),
    path("public/<slug:public_slug>/slots/", PublicBookingSlotsView.as_view(), name="public-slots"),
    path("public/<slug:public_slug>/days/", PublicBookingDaysView.as_view(), name="public-days"),
    path("public/<slug:public_slug>/times/", PublicBookingTimesView.as_view(), name="public-times"),
    path(
        "public/<slug:public_slug>/appointments/",
        PublicBookingCreateView.as_view(),
        name="public-create",
    ),
    path("self-service/<str:token>/", SelfServiceAppointmentView.as_view(), name="self-service"),
    path(
        "self-service/<str:token>/reschedule/",
        SelfServiceRescheduleView.as_view(),
        name="self-reschedule",
    ),
    path("self-service/<str:token>/cancel/", SelfServiceCancelView.as_view(), name="self-cancel"),
]
