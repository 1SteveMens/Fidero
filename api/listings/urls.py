from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.register("listings", views.ListingViewSet, basename="listing")
router.register("reservations", views.ReservationViewSet, basename="reservation")
router.register("enquiries", views.EnquiryViewSet, basename="enquiry")
router.register("seller-screenings", views.SellerScreeningViewSet, basename="seller-screening")

urlpatterns = router.urls
