"""GraphQL documents for homedepot.com's federation gateway
(https://apionline.homedepot.com/federation-gateway/graphql?opname=<op>).

Every document here is a trimmed copy of the one the site's own pages send
(captured 2026-10-14 from search / product / store-locator / daily-deals
pages): the same operation names and argument types, with the tracking,
layout and viewer-only fields left out (sponsored beacons, templates,
discovery zones, buy-it-again, install services, favorites, paint
details, loyalty). The gateway validates documents against its schema, so
a field or argument that stops existing surfaces as a GraphQL
ValidationError (homedepot/fetch.py raises it as an upstream error with
the gateway's message).

Operations
  searchModel               keyword search, category / brand browse (navParam),
                            item-id batches (itemIds) — products + facets
  productClientOnlyProduct  one product's full record
  aislebay                  aisle / bay of store SKUs in one store
  reviews                   paged customer reviews + rating statistics
  questionsAnswers          paged customer questions with their answers
  storeSearch               stores near a ZIP / city / store number / lat,lng
  specialBuyMetadata        the daily / weekly special-buy event + its item ids
"""

# ---- product cards ------------------------------------------------------------
# One card shape for every list (search, browse, item lookups, deals).
PRODUCT_CARD = """
      itemId
      identifiers {
        itemId
        parentId
        productLabel
        brandName
        modelNumber
        storeSkuNumber
        canonicalUrl
        productType
        isSuperSku
        specialOrderSku
      }
      media {
        images {
          url
          type
          subType
          sizes
        }
      }
      pricing(storeId: $storeId, isBrandPricingPolicyCompliant: false) {
        value
        original
        unitOfMeasure
        specialBuy
        message
        mapAboveOriginalPrice
        alternatePriceDisplay
        mapDetail {
          effectiveMap
          percentageOff
          dollarOff
          mapPolicy
        }
        promotion {
          type
          promotionTag
          dollarOff
          percentageOff
          savingsCenter
          savingsCenterPromos
          specialBuySavings
          specialBuyDollarOff
          specialBuyPercentageOff
          experienceTag
          subExperienceTag
          description {
            shortDesc
            longDesc
          }
          dates {
            start
            end
          }
        }
        alternate {
          bulk {
            pricePerUnit
            thresholdQuantity
            value
          }
          unit {
            caseUnitOfMeasure
            unitsOriginalPrice
            unitsPerCase
            value
          }
        }
        clearance {
          value
          dollarOff
          percentageOff
          unitsClearancePrice
        }
        conditionalPromotions {
          promotionId
          promotionTags
          skuItemGroup
          eligibilityCriteria {
            itemGroup
            minThresholdVal
            thresholdType
          }
          reward {
            tiers {
              minThresholdVal
              thresholdType
              rewardVal
              rewardType
              rewardLevel
              maxAllowedRewardAmount
            }
          }
        }
      }
      reviews {
        ratingsReviews {
          averageRating
          totalReviews
        }
      }
      details {
        collection {
          collectionId
          name
          url
        }
        highlights
      }
      info {
        isSponsored
        productDepartment
        categoryHierarchy
        quantityLimit
        returnable
        totalNumberOfOptions
        isGenericProduct
        hidePrice
        ecoRebate
        hasSubscription
        isLiveGoodsProduct
        isBuryProduct
        productSubType {
          name
          link
        }
        swatches {
          isSelected
          itemId
          label
          swatchImgUrl
          url
          value
        }
      }
      badges(storeId: $storeId) {
        name
        label
      }
      availabilityType {
        type
        buyable
        discontinued
        status
      }
      fulfillment(storeId: $storeId, zipCode: $zipCode) {
        fulfillmentOptions {
          type
          fulfillable
          services {
            type
            hasFreeShipping
            freeDeliveryThreshold
            deliveryCharge
            totalCharge
            deliveryTimeline
            deliveryMessage
            earliestDeliveryDate
            deliveryDates {
              startDate
              endDate
            }
            dynamicEta {
              hours
              minutes
            }
            locations {
              isAnchor
              locationId
              storeName
              storePhone
              state
              distance
              type
              curbsidePickupFlag
              isBuyInStoreCheckNearBy
              inventory {
                quantity
                isInStock
                isOutOfStock
                isLimitedQuantity
                isUnavailable
                maxAllowedBopisQty
                minAllowedBopisQty
              }
            }
          }
        }
        anchorStoreStatus
        anchorStoreStatusType
        backordered
        backorderedShipDate
        excludedShipStates
        bossExcludedShipStates
        sthExcludedShipState
        onlineStoreStatus
        onlineStoreStatusType
        seasonStatusEligible
      }
      taxonomy {
        breadCrumbs {
          label
        }
      }
      bundleFlag
"""

# ---- facets / navigation ----------------------------------------------------------
SEARCH_META = """
    searchReport {
      keyword
      totalProducts
      didYouMean
      correctedKeyword
      searchUrl
      translatedFrom
      sortBy
      sortOrder
      pageSize
      startIndex
    }
    metadata {
      canonicalUrl
      searchRedirect
      h1Tag
      contentType
      categoryID
      isStoreDisplay
      productCount {
        inStore
      }
      stores {
        storeId
        storeName
        address {
          postalCode
        }
      }
    }
    taxonomy {
      breadCrumbs {
        label
        dimensionName
        refinementKey
        url
        browseUrl
        deselectUrl
      }
      brandLinkUrl
    }
    relatedResults {
      relatedKeywords {
        keyword
      }
      visualNavs {
        label
        categoryId
        webUrl
        imageId
      }
      universalSearch {
        title
      }
    }
    appliedDimensions {
      label
      isNumericFilter
      refinements {
        label
        refinementKey
        url
      }
    }
    dimensions {
      label
      dimensionId
      isNumericFilter
      isColorSwatch
      isVisualNav
      collapse
      refinements {
        label
        refinementKey
        recordCount
        selected
        url
        imgUrl
        nestedRefinements {
          label
          refinementKey
          recordCount
          url
        }
      }
    }
"""

SEARCH = """query searchModel($keyword: String, $navParam: String, $storeId: String, $zipCode: String, $startIndex: Int, $pageSize: Int, $orderBy: ProductSort, $filter: ProductFilter, $additionalSearchParams: AdditionalParams) {
  searchModel(keyword: $keyword, navParam: $navParam, storeId: $storeId, storefilter: ALL, channel: DESKTOP, isBrandPricingPolicyCompliant: false, additionalSearchParams: $additionalSearchParams) {
    id
""" + SEARCH_META + """
    products(startIndex: $startIndex, pageSize: $pageSize, orderBy: $orderBy, filter: $filter) {
""" + PRODUCT_CARD + """
    }
  }
}"""

# A batch of known item ids (deals, lookups); the gateway caps the batch
# around 25-30 ids per call.
ITEMS = """query specialBuyItems($itemIds: [String], $storeId: String, $zipCode: String, $additionalSearchParams: AdditionalParams) {
  searchModel(itemIds: $itemIds, storeId: $storeId, isBrandPricingPolicyCompliant: false, additionalSearchParams: $additionalSearchParams) {
    products(startIndex: 0) {
""" + PRODUCT_CARD + """
    }
  }
}"""

# ---- one product -----------------------------------------------------------------
PRODUCT = """query productClientOnlyProduct($itemId: String!, $storeId: String, $zipCode: String) {
  product(itemId: $itemId) {
""" + PRODUCT_CARD + """
    identifiers {
      omsThdSku
      upc
      upcGtin13
      brandMainPageUrl
      skuClassification
      sampleId
      toolRentalSkuNumber
      rentalCategory
      rentalSubCategory
    }
    media {
      images {
        altText
      }
      video {
        videoId
        title
        type
        url
        thumbnail
        videoStill
        shortDescription
        longDescription
        uploadDate
        dateModified
        link {
          text
          url
        }
      }
      threeSixty {
        id
        url
      }
      augmentedRealityLink {
        usdz
        image
      }
    }
    info {
      bathRenovation
      label
      augmentedReality
      movingCalculatorEligible
      forProfessionalUseOnly
      replacementOMSID
      hasVisuallySimilar
      classNumber
      subClassNumber
      isInStoreReturnMessageEligible
      paintBrand
      paintFamily
      prop65Warning
      prop65Message
      minimumOrderQuantity
      projectCalculatorEligible
      protectionPlanSku
      eligibleProtectionPlanSkus
      hasServiceAddOns
      sskMin
      sskMax
      unitOfMeasureCoverage
      wasMinPriceRange
      wasMaxPriceRange
      recommendationFlags {
        packages
        frequentlyBoughtTogether
        bundles
        collections
      }
      pipCalculator {
        coverageUnits
        display
        toggle
        defaultAdditionalCoverage
        additionalCoveragePercentage
      }
    }
    taxonomy {
      breadCrumbs {
        url
        browseUrl
        dimensionName
        refinementKey
      }
      brandLinkUrl
    }
    badges(storeId: $storeId) {
      endDate
      message
      creativeImageUrl
    }
    details {
      description
      installation {
        serviceType
        leadGenUrl
      }
    }
    subscription {
      defaultfrequency
      discountPercentage
      subscriptionEnabled
    }
    bundleItems {
      id
      quantity
    }
    specificationGroup {
      specTitle
      specifications {
        specName
        specValue
      }
    }
    keyProductFeatures {
      keyProductFeaturesItems {
        features {
          name
          value
          refinementId
          refinementUrl
        }
      }
    }
    sizeAndFitDetail {
      attributeGroups {
        dimensionLabel
        productType
        attributes {
          attributeName
          dimensions
        }
      }
    }
    bundleSpecificationDetails(storeId: $storeId, zipCode: $zipCode) {
      type
      experienceType
      parents {
        parentId
      }
    }
    seo {
      seoKeywords
      seoDescription
    }
  }
}"""

# ---- stock -----------------------------------------------------------------------------
AISLE_BAY = """query aislebay($storeId: String!, $storeSkuIds: [String!]) {
  aislebay(storeId: $storeId, storeSkuIds: $storeSkuIds) {
    storeSkus {
      storeNumber
      storeSkuId
      aisleBayInfo {
        aisle
        bay
        invLocDesc
        invLocDescFriendly
      }
    }
  }
}"""

# ---- reviews / questions -------------------------------------------------------------
REVIEW_FIELDS = """
      Id
      Title
      ReviewText
      Rating
      RatingRange
      IsRecommended
      IsSyndicated
      SubmissionTime
      UserNickname
      UserLocation
      AuthorId
      TotalPositiveFeedbackCount
      TotalNegativeFeedbackCount
      BadgesOrder
      ContextDataValues {
        Age {
          Value
          ValueLabel
        }
        VerifiedPurchaser {
          Value
        }
      }
      SecondaryRatings {
        Quality {
          Value
          ValueRange
        }
        Value {
          Value
          ValueRange
        }
        EnergyEfficiency {
          Value
          ValueRange
        }
        Features {
          Value
          ValueRange
        }
        Appearance {
          Value
          ValueRange
        }
        EaseOfInstallation {
          Value
          ValueRange
        }
        EaseOfUse {
          Value
          ValueRange
        }
      }
      SecondaryRatingsOrder
      TagDimensions {
        Pro {
          Values
        }
        Con {
          Values
        }
      }
      Photos {
        Id
        Caption
        Sizes {
          normal {
            Url
          }
          thumbnail {
            Url
          }
        }
      }
      Videos {
        VideoId
        VideoUrl
        VideoThumbnailUrl
        VideoIframeUrl
        Caption
        VideoHost
      }
      ClientResponses {
        Date
        Response
        Department
        ResponseSource
      }
      SyndicationSource {
        Name
        ContentLink
        LogoImageUrl
      }
      OriginalProductName
"""


def reviews(filters):
    """The reviews document. `filters` is a GraphQL literal for the
    `filters` argument (its input type is not exposed, so it cannot be a
    typed variable): e.g. '{isVerifiedPurchase: true, starRatings: [5]}'."""
    return """query reviews($itemId: String!, $startIndex: Int, $pagesize: String, $sortBy: String, $searchTerm: String) {
  reviews(itemId: $itemId, startIndex: $startIndex, pagesize: $pagesize, sortBy: $sortBy, searchTerm: $searchTerm, filters: %s) {
    TotalResults
    SortBy {
      mosthelpfull
      newest
      oldest
      highestrating
      lowestrating
      photoreview
    }
    Includes {
      Products {
        store {
          Id
          FilteredReviewStatistics {
            AverageOverallRating
            TotalReviewCount
            RecommendedCount
            NotRecommendedCount
            RatingDistribution {
              RatingValue
              Count
            }
            SecondaryRatingsAveragesOrder
          }
        }
      }
    }
    Results {
%s
    }
  }
}""" % (filters, REVIEW_FIELDS)


QUESTIONS = """query questionsAnswers($itemId: String!, $startindex: Int, $pagesize: Int, $sortBy: String, $searchTerm: String) {
  questionsAnswers(itemId: $itemId, startindex: $startindex, pagesize: $pagesize, sortBy: $sortBy, searchTerm: $searchTerm) {
    TotalResults
    Limit
    Offset
    Results {
      Id
      QuestionSummary
      QuestionDetails
      SubmissionTime
      UserNickname
      AuthorId
      AnswerIds
      TotalAnswerCount
      Photos {
        Id
        Caption
        Sizes {
          normal {
            Url
          }
          thumbnail {
            Url
          }
        }
      }
    }
    Includes {
      Answers {
        AnswerId
        Answer {
          Id
          AnswerText
          UserNickname
          AuthorId
          IsBrandAnswer
          IsFeatured
          ModerationStatus
          LastModificationTime
          LastModeratedTime
          TotalPositiveFeedbackCount
          BadgesOrder
          Photos {
            Id
            Caption
            Sizes {
              normal {
                Url
              }
              thumbnail {
                Url
              }
            }
          }
        }
      }
    }
  }
}"""

# ---- stores -------------------------------------------------------------------------
STORE_FIELDS = """
      storeId
      name
      storeType
      address {
        street
        city
        state
        postalCode
        country
      }
      coordinates {
        lat
        lng
      }
      distance
      phone
      proDeskPhone
      toolRentalPhone
      storeDetailsPageLink
      services {
        loadNGo
        propane
        toolRental
        penske
        keyCutting
        wiFi
        applianceShowroom
        expandedFlooringShowroom
        largeEquipment
        kitchenShowroom
      }
      storeHours {
        monday { open close }
        tuesday { open close }
        wednesday { open close }
        thursday { open close }
        friday { open close }
        saturday { open close }
        sunday { open close }
      }
"""

STORE_SEARCH = """query storeSearch($lat: String, $lng: String, $storeSearchInput: String, $pagesize: String, $storeFeaturesFilter: StoreFeaturesFilter) {
  storeSearch(lat: $lat, lng: $lng, storeSearchInput: $storeSearchInput, pagesize: $pagesize, storeFeaturesFilter: $storeFeaturesFilter) {
    stores {
""" + STORE_FIELDS + """
    }
    suggestedAddresses {
      name
      coordinates {
        lat
        lng
      }
    }
  }
}"""

# ---- deals ---------------------------------------------------------------------------
SPECIAL_BUY = """query specialBuyMetadata {
  specialBuyMetadata(dealType: %s) {
    startDate
    endDate
    tagline
    categoryMetadata {
      name
      tagline
      itemIds
      image {
        url
      }
    }
  }
}"""
